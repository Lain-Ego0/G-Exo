#!/usr/bin/env bash

set -Eeuo pipefail

readonly BITRATE=1000000
readonly TX_QUEUE_LENGTH=1000
readonly CONTROL_PERIOD_MS=5
readonly FEEDBACK_TIMEOUT_MS=30
readonly CAN_TIMEOUT_TICKS=600
readonly TORQUE_LIMIT_NM=6
readonly MIN_BUS_VOLTAGE_BITS=0x41C00000  # 24.0f
readonly MAX_BUS_VOLTAGE_BITS=0x42700000  # 60.0f

# RS02 operation-control damping command:
# t_ff=0, p_set=0, v_set=0, Kp=0, Kd=1.
readonly DAMPING_PAYLOAD="7FFF7FFF00003333"
readonly TORQUE_LIMIT_PAYLOAD="0B7000000000C040"
readonly RUN_MODE_PAYLOAD="0570000000000000"
readonly CAN_TIMEOUT_PAYLOAD="2870000058020000"

readonly -a MOTOR_IDS=(01 02 03 04)

declare -a can_interfaces=()
declare -a configured_interfaces=()
declare -a motor_interfaces=("" "" "" "")
declare -a generator_pids=()
declare -a monitor_pids=()

temporary_directory=""
motors_owned=0
scan_only=0
assume_yes=0

log() {
    printf '[rs02-damping] %s\n' "$*"
}

die() {
    printf '[rs02-damping] ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: sudo ./enable_rs02_damping.sh [--scan-only] [--yes]

  --scan-only  Find motor IDs 1-4 and print their damping commands, but do not
               change motor parameters or enable the motors.
  --yes        Skip the interactive ENABLE confirmation.
EOF
}

require_command() {
    command -v "$1" >/dev/null 2>&1 ||
        die "missing command '$1'; install iproute2, can-utils and coreutils"
}

parse_arguments() {
    while (($#)); do
        case "$1" in
            --scan-only)
                scan_only=1
                ;;
            --yes)
                assume_yes=1
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                usage >&2
                die "unknown argument '$1'"
                ;;
        esac
        shift
    done
}

send_to_motor() {
    local index="$1"
    local can_id="$2"
    local payload="$3"
    local interface="${motor_interfaces[$index]:-}"

    [[ -n "$interface" ]] || return 1
    cansend "$interface" "${can_id}${MOTOR_IDS[$index]}#${payload}"
}

stop_all_motors() {
    local repeat
    local index

    for repeat in 1 2 3; do
        for index in "${!MOTOR_IDS[@]}"; do
            [[ -n "${motor_interfaces[$index]:-}" ]] || continue
            send_to_motor "$index" 0400FD 0000000000000000 \
                >/dev/null 2>&1 || true
        done
        sleep 0.01
    done
}

cleanup() {
    local status="$?"
    local pid
    local interface

    trap - EXIT INT TERM HUP
    set +e

    for pid in "${monitor_pids[@]}" "${generator_pids[@]}"; do
        [[ -n "$pid" ]] && kill "$pid" >/dev/null 2>&1
    done
    for pid in "${monitor_pids[@]}" "${generator_pids[@]}"; do
        [[ -n "$pid" ]] && wait "$pid" >/dev/null 2>&1
    done

    if ((motors_owned)); then
        stop_all_motors
        log "stop command sent three times to all four motors"
    fi

    for interface in "${configured_interfaces[@]}"; do
        ip link set dev "$interface" down >/dev/null 2>&1 || true
    done

    if [[ -n "$temporary_directory" && -d "$temporary_directory" ]]; then
        rm -f -- "$temporary_directory"/*.log
        rmdir -- "$temporary_directory" >/dev/null 2>&1 || true
    fi

    exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

load_can_modules() {
    if command -v modprobe >/dev/null 2>&1; then
        modprobe can >/dev/null 2>&1 || true
        modprobe can_raw >/dev/null 2>&1 || true
        modprobe can_dev >/dev/null 2>&1 || true
        modprobe gs_usb >/dev/null 2>&1 || true
    fi
}

discover_can_interfaces() {
    local path
    local -a discovered=()

    shopt -s nullglob
    for path in /sys/class/net/can*; do
        discovered+=("${path##*/}")
    done
    shopt -u nullglob

    ((${#discovered[@]} > 0)) || die "no SocketCAN interfaces were found"
    mapfile -t can_interfaces < <(printf '%s\n' "${discovered[@]}" | sort -V)
}

setup_can_interface() {
    local interface="$1"
    local details

    ip link show dev "$interface" >/dev/null 2>&1 ||
        die "SocketCAN interface '$interface' does not exist"

    configured_interfaces+=("$interface")
    ip link set dev "$interface" down
    # The K3 gs_usb adapters reject restart-ms, so recovery is handled by the
    # feedback watchdog and a full stop instead of automatic bus restart.
    ip link set dev "$interface" type can bitrate "$BITRATE"
    ip link set dev "$interface" txqueuelen "$TX_QUEUE_LENGTH"
    ip link set dev "$interface" up

    details="$(ip -details link show dev "$interface")"
    grep -q 'can state ERROR-ACTIVE' <<<"$details" || {
        printf '%s\n' "$details" >&2
        die "$interface did not enter CAN ERROR-ACTIVE state"
    }
}

probe_motor_on_interface() {
    local interface="$1"
    local motor_id="$2"
    local response_id="0000${motor_id}FE"
    local log_file="$temporary_directory/probe-${interface}-${motor_id}.log"
    local dump_pid

    timeout 0.5 candump -L -n 1 \
        "${interface},${response_id}:1FFFFFFF" >"$log_file" 2>/dev/null &
    dump_pid="$!"
    sleep 0.03
    cansend "$interface" "0000FD${motor_id}#0000000000000000" \
        >/dev/null 2>&1 || true
    wait "$dump_pid" >/dev/null 2>&1 || true

    grep -Eqi "[[:space:]]${response_id}#" "$log_file"
}

interface_is_used() {
    local candidate="$1"
    local interface

    for interface in "${motor_interfaces[@]}"; do
        [[ "$interface" == "$candidate" ]] && return 0
    done
    return 1
}

scan_all_motors() {
    local interface
    local index
    local motor_id

    for interface in "${can_interfaces[@]}"; do
        log "scanning $interface for motor IDs 1-4"
        for index in "${!MOTOR_IDS[@]}"; do
            motor_id="${MOTOR_IDS[$index]}"
            if probe_motor_on_interface "$interface" "$motor_id"; then
                [[ -z "${motor_interfaces[$index]}" ]] ||
                    die "motor ID 0x${motor_id} answered on both ${motor_interfaces[$index]} and $interface"
                motor_interfaces[$index]="$interface"
                log "found motor ID 0x${motor_id} on $interface"
            fi
        done
    done

    for index in "${!MOTOR_IDS[@]}"; do
        [[ -n "${motor_interfaces[$index]}" ]] ||
            die "motor ID 0x${MOTOR_IDS[$index]} was not found on any CAN interface"
    done

    for interface in "${can_interfaces[@]}"; do
        if ! interface_is_used "$interface"; then
            ip link set dev "$interface" down
        fi
    done
}

print_mapping_and_commands() {
    local index
    local extended_id

    log "unique motor mapping:"
    for index in "${!MOTOR_IDS[@]}"; do
        extended_id="017FFF${MOTOR_IDS[$index]}"
        printf '  ID 0x%s -> %s\n' \
            "${MOTOR_IDS[$index]}" "${motor_interfaces[$index]}"
        printf '    cangen -e -g %s -p 2 -I %s -L 8 -D %s %s\n' \
            "$CONTROL_PERIOD_MS" "$extended_id" "$DAMPING_PAYLOAD" \
            "${motor_interfaces[$index]}"
    done
}

little_endian_float_bits() {
    local payload="$1"
    local little_endian="${payload:8:8}"

    printf '%s%s%s%s\n' \
        "${little_endian:6:2}" "${little_endian:4:2}" \
        "${little_endian:2:2}" "${little_endian:0:2}"
}

read_parameter_payload() {
    local index="$1"
    local parameter="$2"
    local interface="${motor_interfaces[$index]}"
    local motor_id="${MOTOR_IDS[$index]}"
    local response_id="1100${motor_id}FD"
    local log_file="$temporary_directory/read-${index}-${parameter}.log"
    local dump_pid
    local payload

    timeout 1 candump -L -n 1 \
        "${interface},${response_id}:1FFFFFFF" >"$log_file" 2>/dev/null &
    dump_pid="$!"
    sleep 0.03
    send_to_motor "$index" 1100FD "${parameter}000000000000"
    wait "$dump_pid" >/dev/null 2>&1 || true

    payload="$(awk -F'#' 'NF == 2 {gsub(/[[:space:]]/, "", $2); print toupper($2); exit}' "$log_file")"
    [[ ${#payload} -eq 16 ]] ||
        die "motor ${interface}/0x${motor_id} did not return parameter 0x${parameter}"
    printf '%s\n' "$payload"
}

write_and_verify_parameter() {
    local index="$1"
    local expected_payload="$2"
    local description="$3"
    local parameter="${expected_payload:0:4}"
    local actual_payload

    send_to_motor "$index" 1200FD "$expected_payload"
    sleep 0.01
    actual_payload="$(read_parameter_payload "$index" "$parameter")"
    [[ "$actual_payload" == "$expected_payload" ]] ||
        die "motor ${motor_interfaces[$index]}/0x${MOTOR_IDS[$index]} rejected $description: expected $expected_payload, got $actual_payload"
}

check_bus_voltage() {
    local index="$1"
    local payload
    local bits_hex
    local bits

    payload="$(read_parameter_payload "$index" 1C70)"
    bits_hex="$(little_endian_float_bits "$payload")"
    bits=$((16#$bits_hex))

    if ((bits < MIN_BUS_VOLTAGE_BITS || bits > MAX_BUS_VOLTAGE_BITS)); then
        die "motor ${motor_interfaces[$index]}/0x${MOTOR_IDS[$index]} bus voltage is outside the RS02 24-60 V range (raw float 0x${bits_hex})"
    fi
}

prepare_motor() {
    local index="$1"

    send_to_motor "$index" 0400FD 0000000000000000
    sleep 0.01
    send_to_motor "$index" 1800FD 0102030405060000
    sleep 0.01
    write_and_verify_parameter "$index" "$TORQUE_LIMIT_PAYLOAD" \
        "the ${TORQUE_LIMIT_NM} Nm torque limit"
    write_and_verify_parameter "$index" "$RUN_MODE_PAYLOAD" \
        "operation-control mode"
}

start_damping_stream() {
    local index="$1"
    local interface="${motor_interfaces[$index]}"
    local motor_id="${MOTOR_IDS[$index]}"
    local extended_id="017FFF${motor_id}"
    local log_file="$temporary_directory/cangen-${index}.log"

    cangen -e -g "$CONTROL_PERIOD_MS" -p 2 -I "$extended_id" -L 8 \
        -D "$DAMPING_PAYLOAD" "$interface" >"$log_file" 2>&1 &
    generator_pids+=("$!")
}

monitor_motor_feedback() {
    local index="$1"
    local interface="${motor_interfaces[$index]}"
    local motor_id="${MOTOR_IDS[$index]}"
    local filter_id="0200${motor_id}FD"
    local log_file="$temporary_directory/monitor-${index}.log"
    local line
    local frame
    local can_id
    local can_id_value
    local fault_bits

    while IFS= read -r line; do
        frame="${line##* }"
        can_id="${frame%%#*}"
        [[ "$can_id" =~ ^[0-9A-Fa-f]{8}$ ]] || continue
        can_id_value=$((16#$can_id))
        fault_bits=$(((can_id_value >> 16) & 0x3F))
        if ((fault_bits != 0)); then
            printf 'motor %s/0x%s reported fault bits 0x%02X\n' \
                "$interface" "$motor_id" "$fault_bits" >"$log_file"
            return 2
        fi
    done < <(candump -L -T "$FEEDBACK_TIMEOUT_MS" \
        "${interface},${filter_id}:1F00FFFF" 2>>"$log_file")

    printf 'motor %s/0x%s feedback exceeded %s ms\n' \
        "$interface" "$motor_id" "$FEEDBACK_TIMEOUT_MS" >>"$log_file"
    return 1
}

start_feedback_monitor() {
    local index="$1"

    monitor_motor_feedback "$index" &
    monitor_pids+=("$!")
}

capture_feedback_id() {
    local index="$1"
    local interface="${motor_interfaces[$index]}"
    local motor_id="${MOTOR_IDS[$index]}"
    local filter_id="0200${motor_id}FD"
    local log_file="$temporary_directory/feedback-${index}.log"
    local dump_pid
    local frame

    timeout 1 candump -L -n 1 \
        "${interface},${filter_id}:1F00FFFF" >"$log_file" 2>/dev/null &
    dump_pid="$!"
    wait "$dump_pid" >/dev/null 2>&1 || true
    frame="$(awk '{print $NF; exit}' "$log_file")"
    [[ "$frame" == *'#'* ]] || return 1
    printf '%s\n' "${frame%%#*}"
}

verify_motor_enabled() {
    local index="$1"
    local can_id
    local can_id_value
    local mode
    local fault_bits

    can_id="$(capture_feedback_id "$index")" ||
        die "no operation feedback from motor ${motor_interfaces[$index]}/0x${MOTOR_IDS[$index]} after enable"
    can_id_value=$((16#$can_id))
    mode=$(((can_id_value >> 22) & 0x03))
    fault_bits=$(((can_id_value >> 16) & 0x3F))

    ((fault_bits == 0)) ||
        die "motor ${motor_interfaces[$index]}/0x${MOTOR_IDS[$index]} enabled with fault bits 0x$(printf '%02X' "$fault_bits")"
    ((mode == 2)) ||
        die "motor ${motor_interfaces[$index]}/0x${MOTOR_IDS[$index]} did not enter Motor mode (mode=$mode)"
}

check_workers() {
    local index
    local pid
    local reason

    for index in "${!generator_pids[@]}"; do
        pid="${generator_pids[$index]}"
        kill -0 "$pid" >/dev/null 2>&1 ||
            die "the 200 Hz stream for motor ID 0x${MOTOR_IDS[$index]} stopped"
    done

    for index in "${!monitor_pids[@]}"; do
        pid="${monitor_pids[$index]}"
        if ! kill -0 "$pid" >/dev/null 2>&1; then
            reason="$(tail -n 1 "$temporary_directory/monitor-${index}.log" 2>/dev/null || true)"
            die "${reason:-feedback monitor for motor ID 0x${MOTOR_IDS[$index]} stopped}"
        fi
    done
}

check_can_health() {
    local interface
    local -a checked=()
    local seen
    local previous
    local details

    for interface in "${motor_interfaces[@]}"; do
        seen=0
        for previous in "${checked[@]}"; do
            [[ "$previous" == "$interface" ]] && seen=1
        done
        ((seen == 0)) || continue
        checked+=("$interface")

        details="$(ip -details link show dev "$interface")"
        grep -q 'can state ERROR-ACTIVE' <<<"$details" ||
            die "$interface left CAN ERROR-ACTIVE state"
    done
}

confirm_enable() {
    if ((assume_yes)); then
        return
    fi
    [[ -t 0 ]] || die "non-interactive enable requires --yes"

    log "WARNING: active damping regenerates energy; the supply must absorb it"
    log "WARNING: keep the mechanism unloaded and a physical emergency stop ready"
    printf 'Type ENABLE to start active damping on all four motors: '
    local confirmation
    read -r confirmation
    [[ "$confirmation" == "ENABLE" ]] || die "enable cancelled"
}

main() {
    local index
    local loop_count=0

    parse_arguments "$@"
    ((EUID == 0)) || die "run this script as root: sudo $0"

    require_command ip
    require_command cansend
    require_command candump
    require_command cangen
    require_command timeout
    require_command mktemp
    require_command grep
    require_command awk
    require_command sort
    require_command tail
    require_command flock

    exec 9>/run/lock/gexo-rs02-damping.lock
    flock -n 9 || die "another RS02 damping script is already running"

    load_can_modules
    discover_can_interfaces
    temporary_directory="$(mktemp -d /tmp/gexo-rs02-damping.XXXXXX)"

    log "configuring ${#can_interfaces[@]} CAN interfaces at 1 Mbps"
    for index in "${!can_interfaces[@]}"; do
        setup_can_interface "${can_interfaces[$index]}"
    done

    scan_all_motors
    print_mapping_and_commands
    if ((scan_only)); then
        log "scan complete; no motor parameter or enable command was sent"
        return
    fi

    log "checking the RS02 24-60 V bus-voltage requirement"
    for index in "${!MOTOR_IDS[@]}"; do
        check_bus_voltage "$index"
    done

    confirm_enable
    motors_owned=1

    log "stopping motors, setting the 6 Nm limit and selecting operation mode"
    for index in "${!MOTOR_IDS[@]}"; do
        prepare_motor "$index"
    done

    # Operation frames are already flowing before the motor-side timeout and
    # power-stage enable are applied.
    for index in "${!MOTOR_IDS[@]}"; do
        start_damping_stream "$index"
    done
    sleep 0.05

    for index in "${!MOTOR_IDS[@]}"; do
        write_and_verify_parameter "$index" "$CAN_TIMEOUT_PAYLOAD" \
            "the ${FEEDBACK_TIMEOUT_MS} ms (${CAN_TIMEOUT_TICKS} ticks) CAN timeout"
        start_feedback_monitor "$index"
    done
    sleep 0.04
    check_workers

    for index in "${!MOTOR_IDS[@]}"; do
        send_to_motor "$index" 0300FD 0000000000000000
        sleep 0.01
        verify_motor_enabled "$index"
    done

    log "active damping is enabled at 200 Hz with Kd=1 and a ${TORQUE_LIMIT_NM} Nm limit"
    log "press Ctrl+C to stop all motors and close the CAN interfaces"

    while true; do
        sleep 0.01
        check_workers
        loop_count=$((loop_count + 1))
        if ((loop_count % 10 == 0)); then
            check_can_health
        fi
    done
}

main "$@"
