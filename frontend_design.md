# G-Exo Physical AI Robot Cockpit

## Frontend Design System

- Status: Final design specification
- Product: G-Exo four-DOF active lower-limb exoskeleton
- Primary surface: mobile-first local Web control cockpit
- Visual source: `../../G-Exo物理AI黑客松2026-B14-a.pdf`
- Design language: `SENSE -> REASON -> ACT`

## 1. Product Definition

This interface is an operational cockpit for G-Exo operators, developers, and
demo staff. Its single job is to make the robot's live state, decision path,
safety gate, and actuator output understandable at a glance while preserving
the existing control restrictions.

The cockpit is hardware-first. Current G-Exo telemetry comes primarily from:

- Four IMUs
- Four joint encoders
- CAN motor and controller state
- Battery bus voltage and current
- ROS 2 controller acknowledgements

HRV and PPG are not part of the default SENSE surface. They belong to the
future Aloop wearable extension and appear only when that module is explicitly
reported as connected.

## 2. Design Principles

1. **Hardware truth before visual polish.** Missing telemetry displays `--` or
   `Not connected`; the UI never manufactures plausible values.
2. **The closed loop is the information architecture.** SENSE, REASON, and ACT
   are operational stages, not decorative categories.
3. **Safety state is always visible.** E-stop, fault, CAN, stale data, wearer
   motion, and controller acknowledgement cannot be hidden behind a tab.
4. **Commands are not success until acknowledged.** Sent, pending,
   acknowledged, rejected, failed, and timed out are visually distinct.
5. **No direct raw torque control.** The Web UI controls mode and the permitted
   global assist ratio only. Joint torque is monitored, not arbitrarily set.
6. **One signature visual device.** A data-bearing closed-loop spine connects
   sensing, reasoning, actuation, and the telemetry time axis. Other decoration
   stays restrained.

## 3. Poster-Derived Visual Language

The official poster already establishes the core visual system:

- Deep blue-black field from the poster background
- Near-black blue panels with fine cool-blue borders
- Cyan for SENSE
- Purple for REASON
- Yellow for ACT
- Pink for human-risk and biological alerts
- Heavy geometric headings, compact data typography, and short technical copy

The cockpit preserves this language without reproducing the poster as a
marketing page. The exoskeleton product image becomes a functional four-joint
status map inside SENSE. The poster's three-column cards become operational
modules with live state and controls.

### 3.1 Color Roles

| Role | Token | Value | Usage |
|---|---|---:|---|
| Primary background | `--gexo-bg` | `#071426` | Main cockpit field |
| Poster deep background | `--gexo-bg-deep` | `#030F27` | Edge and depth layer |
| Solid panel | `--gexo-surface-solid` | `#0D1323` | Fallback panel color |
| SENSE | `--gexo-sense` | `#23D8F2` | IMU, encoder, CAN sensing |
| REASON | `--gexo-reason` | `#AD8FFF` | Agent and SafetyGuard path |
| ACT | `--gexo-act` | `#FFC424` | Mode and permitted actuation |
| Human risk | `--gexo-human` | `#FF778B` | E-stop, physiology, wearer risk |
| Healthy | `--gexo-success` | `#49D8A0` | Online, acknowledged, calibrated |
| Warning | `--gexo-warning` | `#FF9F43` | Thermal or state warning |
| Critical | `--gexo-danger` | `#FF5C72` | Fault, rejection, timeout |

Color never carries state alone. Every state also has an icon, label, or value.

### 3.2 Typography

- Display and English stage labels: `Barlow Condensed`, 600 or 700
- Chinese interface copy: `Source Han Sans SC`, 400 to 700
- Data, units, latency, IDs: `IBM Plex Mono`, 400 to 600
- Local font assets are preferred; the K3 interface must not depend on a public
  font CDN.
- Stage labels use uppercase with normal letter spacing.
- Large type is reserved for the G-Exo wordmark and primary mode or assist
  value. Panel headings remain compact.

### 3.3 Surface and Shape

- Primary glass panels: dark translucent surface, 16 px backdrop blur, 8 px
  corner radius, and a one-pixel border.
- No cards inside cards. Internal groups use spacing, rules, and alignment.
- Buttons and inputs use a 6 px radius and a stable 44 px minimum height.
- Pills are reserved for live status values, not general containers.
- Glow appears only on the active closed-loop stage or keyboard focus.

## 4. Page Architecture

### 4.1 Desktop Layout

```text
+----------------------------------------------------------------------------+
| G-EXO / PHYSICAL AI   ROBOT READY  E-STOP SAFE  FAULT 0   K3 CONNECTED     |
+----------------------------------------------------------------------------+
| SENSE / CYAN          | REASON / PURPLE             | ACT / YELLOW         |
| IMU 01-04             | Qwen Local Agent            | Assist / Damping     |
| Encoder LH/LK/RH/RK   | User Intent                 | Assist ratio         |
| CAN and motor health  | LLM Intent Parsing          | LH torque Cmd / Act  |
| Four-joint body map   | Safety Validation           | LK torque Cmd / Act  |
|                       | ROS 2 Service               | RH torque Cmd / Act  |
|                       | Actuator                    | RK torque Cmd / Act  |
|--------- SENSE -------------> REASON --------------------> ACT ------------|
+----------------------------------------------------------------------------+
| TELEMETRY 60 s: Joint Angle | Torque | Temperature | Battery / Bus         |
+----------------------------------------------------------------------------+
```

The header and safety rail remain visible while the content scrolls.

### 4.2 Responsive Behavior

| Viewport | Layout |
|---|---|
| `>= 1180px` | Three equal SENSE, REASON, ACT columns; telemetry in a 2x2 grid |
| `768-1179px` | SENSE and REASON in two columns; ACT full width below |
| `< 768px` | Sticky safety rail; SENSE, REASON, ACT tabs; one telemetry chart at a time |

On mobile, a tab switch changes only the center workspace. E-stop, fault, CAN,
connection freshness, and K3 state remain visible at all times.

## 5. Cockpit Header

The top bar contains three functional zones:

1. **G-Exo identity:** poster-derived wordmark plus `PHYSICAL AI COCKPIT`.
2. **Robot Status:** mode, stationary or moving, E-stop, fault, CAN, and last
   telemetry update.
3. **K3 Connected:** connection state, round-trip latency when available, and
   current transport.

The header state priorities are:

```text
Critical fault or E-stop > stale or disconnected > warning > ready
```

A critical state replaces the normal thin safety rail with a full-width alert
band. The alert states the exact blocker and keeps write controls disabled.

## 6. SENSE Module

### 6.1 Default Content

SENSE uses the poster cyan and reflects the current G-Exo hardware stack.

#### IMU Array

- IMU 01 to IMU 04
- Online or offline
- Calibrated or calibration required
- Last sample age when exposed by the controller
- Orientation or acceleration values only when present in the telemetry schema

#### Encoder State

- `LH`: left hip position and velocity
- `LK`: left knee position and velocity
- `RH`: right hip position and velocity
- `RK`: right knee position and velocity

Encoder values use aligned numbers and explicit units: `rad` and `rad/s`.

#### CAN and Motor State

- CAN online state
- Four motor temperatures
- Bus voltage and bus current
- Fault code and message
- State freshness

#### Four-Joint Body Map

The poster exoskeleton image is used as a functional joint map. Four anchored
nodes represent LH, LK, RH, and RK. Node color and label show connection,
temperature severity, and current joint angle. This is the primary visual
signature inside SENSE.

### 6.2 Aloop Future Extension

HRV and PPG do not appear in the default panel, empty state, or telemetry tabs.
An Aloop extension section is mounted only when the backend reports a capability
such as:

```json
{
  "extensions": {
    "aloop": {
      "connected": true,
      "capabilities": ["hrv", "ppg"]
    }
  }
}
```

When connected, Aloop appears as a secondary SENSE source with the poster pink
used only for human physiological risk. It must remain visually distinct from
the core G-Exo hardware telemetry.

## 7. REASON Module

REASON uses the poster purple and presents the operational decision path. It
does not reveal chain-of-thought or hidden model reasoning.

### 7.1 Agent Identity

- Display name: `Qwen Local Agent`
- Actual model identifier is fetched from the backend or model health endpoint
- Status: ready, parsing, waiting for confirmation, unavailable, or failed
- Model name must not be hard-coded in the frontend

### 7.2 SafetyGuard Flow

The primary flow is always presented in this order:

```text
User Intent
    |
    v
LLM Intent Parsing
    |
    v
Safety Validation
    |
    v
ROS 2 Service
    |
    v
Actuator
```

The stage label remains stable while the secondary metadata reflects the real
transport. `ROS 2 Service` is backed by `RosBridgeAdapter`; a topic or service
implementation may be shown as a compact transport subtitle.

Each stage supports these states:

| State | Treatment |
|---|---|
| Idle | Muted node and neutral connector |
| Active | Purple outline and one restrained pulse |
| Passed | Success icon and elapsed time |
| Awaiting confirmation | Yellow pause marker |
| Rejected | Pink or red stop marker plus reason |
| Failed or timed out | Red marker plus exact error |

The event detail may show:

- Parsed intent and whitelisted action
- Source: rule, LLM tool call, or JSON fallback
- SafetyGuard decision and blocker
- Request ID
- ROS 2 send and acknowledgement duration
- Controller result

It must not show hidden reasoning tokens or model chain-of-thought.

### 7.3 Agent Command Surface

The existing natural-language command and document Q&A input lives at the
bottom of REASON. The latest message and latest tool event remain visible;
conversation history opens in a drawer so the decision path stays primary.

## 8. ACT Module

ACT uses the poster yellow and contains both permitted controls and actuator
feedback.

### 8.1 Mode and Assist Controls

- Segmented control: `Assist` and `Damping`
- Mode switch always requires confirmation
- Mode switch is disabled while the wearer is moving
- Assist ratio range: `0.3-1.0`
- Step size: exactly `+0.1` or `-0.1`
- All four joints change together
- Assist adjustment is disabled in Damping mode

### 8.2 Four-Joint Real-Time Torque

The four rows are fixed and keep the controller joint order:

```text
LH  Left hip
LK  Left knee
RH  Right hip
RK  Right knee
```

Each row displays:

- Command Torque
- Actual Torque
- Signed delta: `actual - command`
- Unit: `Nm`
- A compact dual-line or dual-bar comparison
- Warning state when configured deviation or thermal limits are exceeded

Command and Actual use a shared numeric scale so visual length is comparable.
The row order never changes when values update.

### 8.3 Torque Data Integrity

The current state schema exposes `command_torque` and `estimated_torque`. An
estimated value must not be labeled as actual measurement.

The preferred controller contract adds:

```json
{
  "command_torque": [1.5, 2.0, 1.4, 2.1],
  "actual_torque": [1.4, 1.9, 1.5, 2.0]
}
```

Until `actual_torque` exists, the UI uses the explicit label `Estimated Torque`
and the marker `EST`. It may switch to `Actual Torque` only when a measured
field is present.

Raw torque values remain read-only. The Web and LLM layers do not expose a raw
torque, current, CAN frame, or single-joint command input.

## 9. Telemetry Dock

The bottom dock stores 60 seconds of WebSocket snapshots in a client-side ring
buffer. The existing 5 Hz mock stream produces at most 300 raw points per
series. Rendering may decimate points without changing stored values.

### 9.1 Charts

1. **Joint Angle:** LH, LK, RH, RK in `rad`
2. **Torque:** Command and Actual or Estimated, selectable by joint, in `Nm`
3. **Temperature:** Four motor temperatures in degrees Celsius
4. **Battery:** percentage plus optional bus voltage and current

All charts share a synchronized time cursor, pause control, 15/30/60-second
range, and explicit disconnected gaps. A stale period is never connected with
a continuous line.

### 9.2 Series Colors

Stage colors are reserved for SENSE, REASON, and ACT semantics. Joint charts use
a separate series palette:

| Joint | Color |
|---|---:|
| LH | `#23D8F2` |
| LK | `#8EDDE8` |
| RH | `#AD8FFF` |
| RK | `#FF778B` |

Yellow remains available for command torque and active ACT state.

## 10. React Component Architecture

```text
AppShell
|- CockpitHeader
|  |- GExoWordmark
|  |- RobotSafetyRail
|  `- K3ConnectionStatus
|- ClosedLoopDeck
|  |- ClosedLoopSpine
|  |- SensePanel
|  |  |- ImuArray
|  |  |- EncoderReadout
|  |  |- ExoskeletonJointMap
|  |  `- CanMotorHealth
|  |- ReasonPanel
|  |  |- LocalAgentStatus
|  |  |- SafetyGuardFlow
|  |  |- ToolEventDetail
|  |  `- AgentCommandBar
|  `- ActPanel
|     |- ModeSegment
|     |- AssistRatioStepper
|     |- JointTorqueMatrix
|     `- CommandResult
|- TelemetryDock
|  |- TelemetryToolbar
|  |- RealtimeChartGrid
|  `- TelemetryChart
|- ModeConfirmDialog
`- DebugDrawer
```

### 10.1 Hooks and State

| Hook | Responsibility |
|---|---|
| `useRobotSocket` | WebSocket lifecycle, retry, stale state, latest snapshot |
| `useTelemetryBuffer` | 60-second ring buffer and disconnected gaps |
| `useRobotCommand` | Action submission, confirmation, acknowledgement, timeout |
| `useAgentEvents` | Intent, SafetyGuard, ROS 2, and actuator stage events |
| `useResponsiveDeck` | Desktop grid and mobile stage tabs |

No React component writes directly to ROS 2. All writes continue through the
existing HTTP action and confirmation endpoints.

## 11. Data Contract Mapping

### 11.1 Available Now

| UI | Current field |
|---|---|
| Mode | `mode` |
| Assist ratio | `assist_ratio` |
| Stationary state | `is_stationary` |
| Joint angle | `joint_position[4]` |
| Joint velocity | `joint_velocity[4]` |
| Command torque | `command_torque[4]` |
| Estimated torque | `estimated_torque[4]` |
| Motor temperature | `motor_temperature[4]` |
| Battery | `battery_percent`, `bus_voltage`, `bus_current` |
| IMU health | `imu_online[4]`, `imu_calibrated[4]` |
| Safety | `can_online`, `emergency_stop`, `fault_code`, `fault_message` |

### 11.2 Derived in Frontend

- Maximum motor temperature
- Torque deviation
- State age and connection freshness
- 60-second chart history
- Per-motor severity
- Closed-loop event presentation from command results

### 11.3 Backend Extensions

| Need | Proposed field or event |
|---|---|
| Measured torque | `actual_torque[4]` |
| Agent pipeline | `agent_stage`, `stage_status`, `stage_duration_ms` |
| Intent source | `intent_source: rule | tool | json` |
| Tool event | action, parameters, request ID, result |
| Model status | model ID, reachable, latency |
| Detailed IMU values | timestamped orientation or acceleration fields |
| Future Aloop | capability-gated HRV and PPG extension payload |

## 12. CSS Tokens

```css
:root {
  --gexo-bg: #071426;
  --gexo-bg-deep: #030f27;
  --gexo-surface: rgba(13, 19, 35, 0.78);
  --gexo-surface-solid: #0d1323;
  --gexo-surface-raised: rgba(18, 28, 49, 0.92);
  --gexo-border: rgba(137, 165, 214, 0.2);
  --gexo-rule: rgba(137, 165, 214, 0.12);

  --gexo-text: #f4f7ff;
  --gexo-text-muted: #91a3c6;
  --gexo-text-dim: #647696;
  --gexo-sense: #23d8f2;
  --gexo-reason: #ad8fff;
  --gexo-act: #ffc424;
  --gexo-human: #ff778b;
  --gexo-success: #49d8a0;
  --gexo-warning: #ff9f43;
  --gexo-danger: #ff5c72;

  --font-display: "Barlow Condensed", "Source Han Sans SC", sans-serif;
  --font-ui: "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  --font-data: "IBM Plex Mono", Consolas, monospace;

  --text-xs: 0.6875rem;
  --text-sm: 0.8125rem;
  --text-md: 0.9375rem;
  --text-lg: 1.25rem;
  --text-xl: 1.75rem;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  --radius-panel: 8px;
  --radius-control: 6px;
  --panel-blur: 16px;
  --control-height: 44px;
  --icon-control-size: 36px;
  --header-height: 64px;
  --chart-height: 168px;

  --motion-fast: 120ms;
  --motion-state: 240ms;
}
```

Use an opaque `--gexo-surface-solid` fallback when `backdrop-filter` is not
supported or reduced visual effects are requested.

## 13. Interaction and Motion

- The closed-loop spine pulses only when an actual event advances to a new
  stage. It is not an ambient looping animation.
- Live numbers update without resizing their containers.
- Command controls show pending state immediately but success only after the
  controller acknowledgement.
- Tooltips name unfamiliar icons; controls retain visible keyboard focus.
- `prefers-reduced-motion` disables spine pulses and animated chart transitions.
- Touch targets are at least 44 by 44 px.

## 14. Empty, Offline, and Fault States

- **No state yet:** `Waiting for controller telemetry` with all writes disabled.
- **Stale:** retain the last values, mark them stale, show their age, and break
  chart lines at the stale boundary.
- **CAN offline:** SENSE motor nodes and ACT torque rows enter blocked state.
- **E-stop or fault:** show the exact code and message; all writes remain
  disabled. The UI never offers E-stop release.
- **Agent unavailable:** direct permitted buttons remain available when the
  safety state permits them.
- **Missing Actual Torque:** show `Estimated Torque (EST)` rather than silently
  substituting an estimated value.
- **Aloop absent:** do not render HRV or PPG controls, cards, or empty charts.

## 15. Implementation Boundaries

- Recommended frontend: React with Vite, compiled to static assets served by
  the existing FastAPI application.
- Reuse the current `/api/state`, `/api/action`, `/api/confirm`, `/api/chat`,
  and `/ws` routes.
- Preserve `RosBridgeAdapter`; do not hard-code ROS transport in React.
- Use Lucide icons for standard controls and status symbols.
- Use the poster exoskeleton asset only for the functional joint map.
- Avoid large runtime dependencies where a small chart renderer is sufficient.
- Do not expose model-generated shell execution, raw motor writes, or safety
  configuration changes.

## 16. Acceptance Criteria

The implementation is visually and functionally complete when:

1. The first viewport clearly reads as G-Exo and preserves the poster's
   SENSE, REASON, ACT color language.
2. SENSE defaults to IMU, encoder, CAN, motor, and joint information only.
3. HRV and PPG are absent unless the Aloop capability is connected.
4. REASON visibly follows `User Intent -> LLM Intent Parsing -> Safety
   Validation -> ROS 2 Service -> Actuator`.
5. The SafetyGuard result, request state, and controller acknowledgement are
   never hidden.
6. ACT shows LH, LK, RH, and RK Command Torque versus Actual Torque, or clearly
   labeled Estimated Torque when measured data is unavailable.
7. Mode and assist controls preserve all existing confirmation and safety
   restrictions.
8. Joint angle, torque, temperature, and battery charts update from live state
   and show disconnected gaps.
9. Desktop, tablet, and mobile layouts have no clipped text, overlapping
   controls, or layout shifts.
10. Keyboard focus, reduced motion, offline, stale, fault, and empty states are
    verified before release.
