// 任务枚举与通用错误文案（JobStatus/JobOutcome/OutcomeSource/ModeSource）。

/// 任务执行状态（API 枚举）。
class JobStatus {
  static const running = 'running';
  static const done = 'done';
  static const error = 'error';
  static const cancelled = 'cancelled';
  static const interrupted = 'interrupted';

  static const all = <String>[
    running,
    done,
    error,
    cancelled,
    interrupted,
  ];

  static String label(String? status) {
    switch (status) {
      case running:
        return '进行中';
      case done:
        return '已完成';
      case error:
        return '失败';
      case cancelled:
        return '已取消';
      case interrupted:
        return '已中断';
      default:
        return '未知状态';
    }
  }
}

/// 交付结果（API 兼容枚举）。
class JobOutcome {
  static const fidelitySuccess = 'fidelity_success';
  static const fidelityDegraded = 'fidelity_degraded';
  static const fastFallback = 'fast_fallback';
  static const fastSuccess = 'fast_success';
  static const failed = 'failed';
  static const cancelled = 'cancelled';

  static const all = <String>[
    fidelitySuccess,
    fidelityDegraded,
    fastFallback,
    fastSuccess,
    failed,
    cancelled,
  ];

  static String label(String? outcome) {
    switch (outcome) {
      case fidelitySuccess:
        return '高保真成功';
      case fidelityDegraded:
        return '降级交付';
      case fastFallback:
        return '快速保底';
      case fastSuccess:
        return '快速成功';
      case failed:
        return '生成失败';
      case cancelled:
        return '已取消';
      default:
        return '未知结果';
    }
  }
}

/// 交付结果来源：显式记录 / 兼容推导 / 无记录。
class OutcomeSource {
  static const result = 'result';
  static const derived = 'derived';
  static const none = 'none';

  static String? normalize(String? raw) {
    switch (raw) {
      case result:
      case derived:
      case none:
        return raw;
      default:
        return null;
    }
  }
}

/// 生成模式来源：job / result / run_record / default。
class ModeSource {
  static const job = 'job';
  static const result = 'result';
  static const runRecord = 'run_record';
  static const defaultValue = 'default';

  static String? normalize(String? raw) {
    switch (raw) {
      case job:
      case result:
      case runRecord:
      case defaultValue:
        return raw;
      default:
        return null;
    }
  }
}

