/// Lifecycle states of algorithm verification.
enum AlgorithmVerifyState {
  /// Idle state, no measurement running.
  idle,

  /// Verification is in progress and collecting data.
  verifying,

  /// The measurement is in the process of stopping.
  stopping,
}

extension AlgorithmVerifyStateExtension on AlgorithmVerifyState {
  bool get isIdle => this == AlgorithmVerifyState.idle;

  bool get isVerifying => this == AlgorithmVerifyState.verifying;

  bool get isStopping => this == AlgorithmVerifyState.stopping;

  /// Whether the user can start a new measurement.
  bool get canStart => isIdle;

  /// Whether the user can stop the current verification measurement.
  bool get canStop => isVerifying;

  /// Whether the user can switch measurement modes.
  bool get canSwitchMode => isIdle;
}
