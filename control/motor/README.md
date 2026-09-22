# RS02 motor layer

This directory follows the small part of the `SDU-ROBOCON/socket-motor`
organization that is useful here:

```text
high-level action or command
        -> Rs02MotorGroup (four fixed joint pointers)
        -> Rs02Motor (one SocketCAN socket and one motor)
        -> RS02 extended CAN frame
```

There is no ROS, LCM, extra thread, model runtime, calibration state machine, or
brand-specific code from the reference project.

## Fixed mapping

| Joint | SocketCAN | Motor ID |
| --- | --- | --- |
| Left hip | `can0` | `0x01` |
| Left knee | `can0` | `0x02` |
| Right hip | `can1` | `0x03` |
| Right knee | `can1` | `0x04` |

The mapping is constructed in `Rs02MotorGroup`; callers do not need to build
CAN IDs or select a channel manually.

## API layers

`Rs02Motor` is the single-motor API:

```cpp
motor.open();
motor.set_motion_mode();
motor.set_torque_limit(6.0F);
motor.enable();
motor.damping(0.2F);             // Kd only
motor.torque(1.0F);              // torque only
motor.position(0.5F, 20.0F, 1.0F);
motor.velocity(1.0F, 0.5F);
motor.update_feedback();
motor.read_bus_voltage(&vbus);   // slow, on-demand read
motor.stop();
```

The four convenience methods all use RS02 `run_mode=0` motion control. They
only fill different fields in the same command:

| Method | `position` | `velocity` | `torque` | `Kp` | `Kd` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `damping(kd)` | 0 | 0 | 0 | 0 | `kd` |
| `torque(tau)` | 0 | 0 | `tau` | 0 | 0 |
| `position(q,kp,kd)` | `q` | 0 | 0 | `kp` | `kd` |
| `velocity(v,kd)` | 0 | `v` | 0 | 0 | `kd` |

`Rs02MotorGroup` only adds mapping and batch operations:

```cpp
Rs02MotorGroup motors;
motors.open_all();
motors.configure_all(6.0F, 600);  // 6 Nm; CAN timeout is about 30 ms
motors.damping_all(0.2F);
motors.enable_all();

Rs02MotorGroup::Commands commands{};
commands[0] = make_torque_command(0.5F);
commands[1] = make_position_command(0.2F, 10.0F, 0.5F);
commands[2] = make_velocity_command(0.3F, 0.5F);
commands[3] = make_damping_command(0.2F);
motors.send_all(commands);
motors.update_all();
motors.stop_all();
```

The group rejects a command whose feed-forward torque exceeds the configured
6 N·m project limit. The single-motor protocol encoder still supports the
RS02 wire range; project-level limiting belongs at the group/RL boundary.

`Rs02Feedback` contains position, velocity, measured torque, temperature, mode,
fault bits, sequence number, and receive time. `read_mechanical_position`,
`read_mechanical_velocity`, `read_iq`, and `read_bus_voltage` use communication
type 17 and must not be called in the 200 Hz loop. The loop should use
`update_all()`, which drains type-2 feedback without blocking on one motor.

## 200 Hz damping demo

The demo is intentionally the only place that owns the periodic loop:

```text
update_all()
-> check valid/fault/feedback age
-> damping_all(Kd)
-> wait for the next absolute 5 ms deadline
```

Build the motor layer without the ONNX deployment dependency:

```bash
cmake -S G-Exo/control -B G-Exo/control/build-rs02 -G Ninja \
  -DBUILD_TESTING=ON -DGEXO_BUILD_DEPLOY=OFF
cmake --build G-Exo/control/build-rs02 --target gexo_rs02_damping_demo
ctest --test-dir G-Exo/control/build-rs02 --output-on-failure
```

After configuring `can0` and `can1` at 1 Mbps, start with a low value:

```bash
sudo G-Exo/control/build-rs02/motor/gexo_rs02_damping_demo 0.2
```

No argument also uses `Kd=0.2`; the accepted range is `(0, 5]`. Keep the
mechanism unloaded and a physical power cutoff within reach. Ctrl+C sends the
RS02 stop command.

The operation-control frame encoder is tested against the `Kd=1` frame:

```text
017FFF01#7FFF7FFF00003333
```

This is pure damping impedance control:

$$
\tau = K_d(0-\dot q)
$$

The RS02 manual states that changing run modes requires stopping first. This
layer therefore keeps all convenience methods in run mode 0; dedicated PP/CSP
or velocity modes can be added later without changing the SocketCAN layer.
