// 任务/API DTO 统一出口：兼容既有 import 'models/job.dart' 的调用方，
// 具体类型拆分到同目录各文件（单文件行数受项目规范约束）。
export 'job_core.dart';
export 'job_detail.dart';
export 'job_summary.dart';
export 'service_info.dart';
