// 单任务快照与轮询器：
// - 每个任务独立缓存、独立轮询、独立错误状态，绝不串用数据；
// - 日志按前缀合并增量，噪音淘汰导致重排时整表替换（与 Web 同一语义）；
// - 轮询只在 APP 前台运行，连续失败 5 次停止并给出可恢复错误。
import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/api_error.dart';
import '../models/job.dart';

/// 单任务前端快照。
class JobSnapshot extends ChangeNotifier {
  JobSnapshot(this.id);

  final String id;

  JobDetail? detail;

  /// 最近一次拉取错误（不影响已有 detail 展示）。
  String? error;

  /// 是否正在拉取。
  bool loading = false;

  /// 是否来自本地缓存（尚未用服务端校准）。
  bool stale = false;

  /// 合并后的日志（实时视图使用）。
  List<LogEntry> logs = const <LogEntry>[];

  /// 日志是否发生过整表重置（UI 需要重建列表）。
  bool logsReset = false;

  /// 从缓存恢复。
  void adoptFromCache(JobDetail cached) {
    detail = cached;
    logs = cached.logs;
    logsReset = true;
    stale = true;
    error = null;
    notifyListeners();
  }

  /// 合并服务端快照。
  void adopt(JobDetail next) {
    _takeLogs(next.logs);
    detail = next;
    stale = false;
    error = null;
    notifyListeners();
  }

  void markLoading() {
    if (loading) return;
    loading = true;
    notifyListeners();
  }

  void markFetchError(Object e) {
    loading = false;
    error = e is ApiError ? e.displayMessage : e.toString();
    notifyListeners();
  }

  void markFetched() {
    loading = false;
  }

  /// 取消成功后立即更新本地状态（服务端 worker 在下一个取消点停止，状态以服务端为准）。
  void markCancelledLocally() {
    final current = detail;
    if (current == null) return;
    detail = JobDetail(
      id: current.id,
      status: JobStatus.cancelled,
      live: null,
      logs: current.logs,
      result: current.result,
      desc: current.desc,
      startedAt: current.startedAt,
      mode: current.mode,
      modeSource: current.modeSource,
      retryOf: current.retryOf,
      outcome: current.outcome ?? JobOutcome.cancelled,
      outcomeSource: current.outcomeSource,
      design: current.design,
      progress: current.progress,
      stage: current.stage,
      views: current.views,
      thinking: null,
    );
    notifyListeners();
  }

  void _takeLogs(List<LogEntry> incoming) {
    final previous = logs;
    var prefix = incoming.length >= previous.length;
    if (prefix) {
      for (var i = 0; i < previous.length; i++) {
        if (!_sameLog(previous[i], incoming[i])) {
          prefix = false;
          break;
        }
      }
    }
    if (prefix) {
      logsReset = false;
      logs = <LogEntry>[...previous, ...incoming.sublist(previous.length)];
    } else {
      logsReset = true;
      logs = incoming;
    }
  }

  static bool _sameLog(LogEntry a, LogEntry b) =>
      a.ts == b.ts && a.kind == b.kind && a.text == b.text;
}

/// 单任务轮询器（按任务独立，不共享长请求）。
class JobPoller {
  JobPoller({
    required this.id,
    required this.fetch,
    required this.onUpdate,
    required this.onError,
    required this.onStop,
    this.interval = const Duration(milliseconds: 900),
    this.maxFailures = 5,
  });

  final String id;

  /// 拉取一次任务详情。
  final Future<JobDetail> Function() fetch;

  /// 每次成功拉到快照（含终态那一次）。
  final void Function(JobDetail detail) onUpdate;

  /// 连续失败达到上限时回调（不再自动轮询）。
  final void Function(String message) onError;

  /// 任务进入终态或停止轮询时回调。
  final void Function() onStop;

  final Duration interval;
  final int maxFailures;

  bool _active = false;
  bool _disposed = false;
  int _fails = 0;

  bool get active => _active;

  void start() {
    if (_active || _disposed) return;
    _active = true;
    unawaited(_loop());
  }

  void stop() {
    _active = false;
  }

  void dispose() {
    _disposed = true;
    _active = false;
  }

  Future<void> _loop() async {
    while (_active && !_disposed) {
      JobDetail detail;
      try {
        detail = await fetch();
        _fails = 0;
      } catch (e) {
        if (_disposed) return;
        _fails++;
        if (_fails >= maxFailures) {
          _active = false;
          onError('与服务端通信失败 $_fails 次，已停止轮询：${e is ApiError ? e.message : e}');
          onStop();
          return;
        }
        await Future<void>.delayed(const Duration(milliseconds: 1200));
        continue;
      }
      if (_disposed) return;
      onUpdate(detail);
      if (detail.status != JobStatus.running) {
        _active = false;
        onStop();
        return;
      }
      await Future<void>.delayed(interval);
    }
  }
}
