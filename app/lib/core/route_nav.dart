// 任务入口统一落点：所有「点开某个任务」的入口都必须走本文件，
// 保证进行中 → 生成进度、已完成且有产物 → 作品详情、失败/取消/中断/无产物 → 生成记录。
// 页面之间跳转同样统一从这里发起，避免各处重复拼路由。
import 'package:flutter/material.dart';

import '../app_scope.dart';
import '../models/job.dart';
import '../pages/mine/diagnostics_page.dart';
import '../pages/mine/mine_page.dart';
import '../pages/mine/rules_page.dart';
import '../pages/mine/service_page.dart';
import '../pages/progress/generation_progress_page.dart';
import '../pages/record/generation_record_page.dart';
import '../pages/settings/setup_page.dart';
import '../pages/shell/root_tabs.dart';
import '../pages/work/assembly_guide_page.dart';
import '../pages/work/part_list_page.dart';
import '../pages/work/work_detail_page.dart';
import 'app_state.dart';

/// 任务默认落点。
enum JobLanding {
  /// 进行中：生成进度页。
  progress,

  /// 已完成且有可用产物：作品详情页。
  work,

  /// 失败/取消/中断或没有可用产物：生成记录页。
  record,
}

/// 依据真实任务详情判定默认落点；不猜测、不伪造。
JobLanding landingOf(JobDetail detail) {
  if (detail.isRunning) return JobLanding.progress;
  final result = detail.result;
  if (detail.isDoneSuccess &&
      result != null &&
      result.modelPath != null &&
      result.solutionPath != null) {
    return JobLanding.work;
  }
  return JobLanding.record;
}

Route<void> _route(Widget page) =>
    MaterialPageRoute<void>(builder: (_) => page);

void _push(BuildContext context, Widget page, {bool replace = false}) {
  final navigator = Navigator.of(context);
  if (replace) {
    navigator.pushReplacement(_route(page));
  } else {
    navigator.push(_route(page));
  }
}

/// 打开任务的默认落点页面：缺详情或快照已过期时先拉取真实数据再判定。
Future<void> openJobById(BuildContext context, String jobId) async {
  final app = AppScope.read(context);
  final snapshot = app.jobs[jobId];
  var detail = snapshot?.detail;
  if (detail == null || (snapshot?.stale ?? false)) {
    try {
      detail = await app.fetchJob(jobId);
    } catch (_) {
      // 拉取失败仍进入生成记录页，由该页展示真实错误与重试入口。
    }
  }
  if (!context.mounted) return;
  final landing = detail == null ? JobLanding.record : landingOf(detail);
  await app.selectJob(jobId);
  if (!context.mounted) return;
  switch (landing) {
    case JobLanding.progress:
      _push(context, GenerationProgressPage(jobId: jobId));
    case JobLanding.work:
      _push(context, WorkDetailPage(jobId: jobId));
    case JobLanding.record:
      _push(context, GenerationRecordPage(jobId: jobId));
  }
}

/// 打开生成进度页。
Future<void> openGenerationProgressPage(
  BuildContext context,
  String jobId, {
  bool replace = false,
}) async {
  await AppScope.read(context).selectJob(jobId);
  if (!context.mounted) return;
  _push(context, GenerationProgressPage(jobId: jobId), replace: replace);
}

/// 打开作品详情页。
void openWorkDetailPage(
  BuildContext context,
  String jobId, {
  bool replace = false,
}) {
  _push(context, WorkDetailPage(jobId: jobId), replace: replace);
}

/// 打开拼装指导页。
void openAssemblyGuidePage(
  BuildContext context,
  String jobId, {
  bool replace = false,
}) {
  _push(context, AssemblyGuidePage(jobId: jobId), replace: replace);
}

/// 打开零件清单页。
void openPartListPage(BuildContext context, String jobId) {
  _push(context, PartListPage(jobId: jobId));
}

/// 打开生成记录页。
void openGenerationRecordPage(
  BuildContext context,
  String jobId, {
  bool replace = false,
}) {
  _push(context, GenerationRecordPage(jobId: jobId), replace: replace);
}

/// 切到底部主导航并关闭压在主界面上的页面。
void gotoMainTab(BuildContext context, int index) {
  RootTabsScope.read(context).select(index);
  Navigator.of(context).popUntil((route) => route.isFirst);
}

/// 打开「我的 → 服务连接」。
void openServicePage(BuildContext context) {
  _push(context, const ServicePage());
}

/// 打开「我的 → 生成规则」。
void openRulesPage(BuildContext context) {
  _push(context, const RulesPage());
}

/// 打开「我的 → 诊断与高级」。
void openDiagnosticsPage(BuildContext context) {
  _push(context, const DiagnosticsPage());
}

/// 打开「我的」。
void openMinePage(BuildContext context) {
  _push(context, const MinePage());
}

/// 打开首次连接引导（未配置服务时）。
void openSetupPage(BuildContext context) {
  _push(context, const SetupPage());
}

/// 打开某任务快照对应的页面时使用的辅助：返回当前快照详情（不触发网络）。
JobDetail? cachedDetail(AppState app, String jobId) => app.jobs[jobId]?.detail;
