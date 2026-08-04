/// History data sync state.
enum HistorySyncState {
  /// Idle state (sync not started).
  idle,

  /// Syncing.
  syncing,

  /// Sync complete.
  completed,

  /// Sync error.
  error,
}

/// History data sync state extension.
extension HistorySyncStateExtension on HistorySyncState {
  /// Whether syncing is in progress.
  bool get isSyncing => this == HistorySyncState.syncing;

  /// Whether syncing has completed.
  bool get isCompleted => this == HistorySyncState.completed;

  /// Whether an error occurred.
  bool get isError => this == HistorySyncState.error;

  /// Whether idle.
  bool get isIdle => this == HistorySyncState.idle;

  /// Returns the state description.
  String get description {
    switch (this) {
      case HistorySyncState.idle:
        return 'Not started';
      case HistorySyncState.syncing:
        return 'Syncing...';
      case HistorySyncState.completed:
        return 'Sync complete';
      case HistorySyncState.error:
        return 'Sync failed';
    }
  }

  /// Returns the state icon.
  String get icon {
    switch (this) {
      case HistorySyncState.idle:
        return '⏸️';
      case HistorySyncState.syncing:
        return '🔄';
      case HistorySyncState.completed:
        return '✅';
      case HistorySyncState.error:
        return '❌';
    }
  }
}
