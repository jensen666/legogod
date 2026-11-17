// 创作页：只负责新建作品与入口。
// 首屏自上而下：需求输入卡（标题「想拼什么？」+ 输入框 + 最多 3 个示例 chip）、
// 快速/高保真紧凑分段 + 当前模式一句说明 + 「模式说明」入口、默认收起的「生成规则」。
// 底部固定全宽主按钮「生成作品」。不再嵌入实时舞台、任务切换器、日志或产物按钮。
// 有进行中任务时只显示一条紧凑摘要（点击进入「作品」页进行中分段）；
// 无进行中任务时显示最近最多 3 个已完成作品，每张卡片只有整卡单一跳转。
// 草稿与模式保存在 AppState：提交防重复，失败保留草稿并原样展示服务端真实错误。
import 'dart:async';

import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/format.dart';
import '../../core/route_nav.dart';
import '../../core/theme.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';

/// 示例需求（与 Web 一致的三个示例）：[0] 为 chip 文案，[1] 为填入输入框的完整需求。
const List<List<String>> examplePrompts = [
  ['中世纪城堡', '一座中世纪城堡：四座角楼、城墙带垛口、正面大门，目标 300 块积木'],
  ['三桅大帆船', '一艘大帆船：船身、三根桅杆挂帆，目标 200 块积木'],
  ['垂耳小狗', '一只站着的小狗：垂耳、黑鼻子、眼睛、短腿'],
];

/// 创作页。
class CreatePage extends StatefulWidget {
  const CreatePage({super.key});

  @override
  State<CreatePage> createState() => _CreatePageState();
}

class _CreatePageState extends State<CreatePage> {
  /// 需求输入控制器：初始值取 AppState 中保留的草稿。
  late final TextEditingController _descCtrl;

  /// 输入框焦点（提交时收起键盘）。
  final FocusNode _descFocus = FocusNode();

  /// 提交中：主按钮禁用，防止重复创建真实任务。
  bool _submitting = false;

  /// 上一次提交失败文案（服务端 64KB/真实错误原样展示）。
  String? _submitError;

  @override
  void initState() {
    super.initState();
    _descCtrl = TextEditingController(text: AppScope.read(context).draftDesc);
  }

  @override
  void dispose() {
    _descCtrl.dispose();
    _descFocus.dispose();
    super.dispose();
  }

  /// 示例 chip：填入完整需求并同步草稿。
  void _fillExample(String text) {
    _descCtrl.text = text;
    _descCtrl.selection = TextSelection.fromPosition(
      TextPosition(offset: text.length),
    );
    AppScope.read(context).setDraftDesc(text);
    setState(() => _submitError = null);
  }

  /// 输入变化：实时写入草稿（落盘去抖由 AppState 处理），并清除上一次提交错误。
  void _onDescChanged(String value) {
    AppScope.read(context).setDraftDesc(value);
    if (_submitError != null) setState(() => _submitError = null);
  }

  /// 提交生成任务：
  /// 空白需求本地拦截；提交原文与用户所见模式；失败保留草稿与模式并展示真实错误；
  /// 成功进入新任务的生成进度页（push，返回键回到创作页可继续准备下一个作品）。
  Future<void> _start() async {
    if (_submitting) return;
    final app = AppScope.read(context);
    final text = _descCtrl.text;
    if (text.trim().isEmpty) {
      setState(() => _submitError = '请先描述想拼的作品（不能是空白内容）。');
      return;
    }
    setState(() {
      _submitting = true;
      _submitError = null;
    });
    _descFocus.unfocus();
    String? newId;
    try {
      // 提交用户输入原文（服务端按契约裁剪首尾空白），显式带上用户所见模式。
      newId = await app.createJob(desc: text, mode: app.draftMode);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _submitError = '启动失败：${describeError(e)}';
      });
      return;
    }
    if (!mounted) return;
    // 先恢复可提交状态：从进度页返回后可直接准备并提交下一个作品。
    setState(() => _submitting = false);
    await openGenerationProgressPage(context, newId);
  }

  /// 打开「模式说明」弹层：两档完整对比 + 生成规则全文（不占用首屏）。
  Future<void> _openModeHelp() async {
    final maxHeight = MediaQuery.sizeOf(context).height * 0.78;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.bgElevated,
      builder: (sheetContext) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: maxHeight),
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 20),
            children: [
              const Text(
                '模式说明',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 10),
              const Text(
                modeComparisonText,
                style: TextStyle(fontSize: 12.5, height: 1.6),
              ),
              const Divider(height: 28),
              const Text(
                '生成规则',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              const Text(
                generationRulesText,
                style: TextStyle(fontSize: 12, height: 1.6, color: AppColors.textMuted),
              ),
              const SizedBox(height: 16),
              OutlinedButton(
                onPressed: () => Navigator.of(sheetContext).pop(),
                child: const Text('关闭'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('创作')),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
          children: [
            _buildRequirementCard(),
            if (_submitError != null) ...[
              const SizedBox(height: 10),
              InfoBanner(text: _submitError!, icon: '⚠️', tone: 'bad'),
            ],
            const SizedBox(height: 16),
            _buildModeSection(app),
            const SizedBox(height: 4),
            _buildRulesSection(),
            const SizedBox(height: 12),
            if (app.runningCount > 0)
              _buildRunningSummary(app)
            else
              _buildRecentWorks(app),
          ],
        ),
      ),
      bottomNavigationBar: BottomPrimaryBar(child: _buildStartButton()),
    );
  }

  /// 需求输入卡：标题「想拼什么？」+ 多行输入框 + 示例 chip。
  Widget _buildRequirementCard() {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            '想拼什么？',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          TextField(
            key: const Key('requirement-input'),
            controller: _descCtrl,
            focusNode: _descFocus,
            onChanged: _onDescChanged,
            minLines: 3,
            maxLines: 7,
            keyboardType: TextInputType.multiline,
            textInputAction: TextInputAction.newline,
            decoration: const InputDecoration(
              hintText: '描述想要拼的作品，例如：一座中世纪城堡，四座角楼，目标 300 块积木',
              alignLabelWithHint: true,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              for (final example in examplePrompts.take(3))
                ActionChip(
                  label: Text(example[0], style: const TextStyle(fontSize: 12)),
                  onPressed: () => _fillExample(example[1]),
                  backgroundColor: AppColors.surfaceHigh,
                  side: const BorderSide(color: AppColors.border),
                ),
            ],
          ),
        ],
      ),
    );
  }

  /// 模式分段：紧凑分段控件 + 当前模式的一句说明 + 「模式说明」入口。
  Widget _buildModeSection(AppState app) {
    final index = app.draftMode == 'fidelity' ? 1 : 0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        KeyedSubtree(
          key: const Key('mode-segment'),
          child: SegmentedControl(
            items: const [SegmentedItem('快速'), SegmentedItem('高保真')],
            index: index,
            onChanged: (value) =>
                app.setDraftMode(value == 1 ? 'fidelity' : 'fast'),
          ),
        ),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(
                  modeLine(app.draftMode),
                  style: const TextStyle(
                    fontSize: 11.5,
                    color: AppColors.textMuted,
                    height: 1.45,
                  ),
                ),
              ),
            ),
            TextButton(
              key: const Key('mode-help'),
              onPressed: _openModeHelp,
              child: const Text('模式说明', style: TextStyle(fontSize: 12)),
            ),
          ],
        ),
      ],
    );
  }

  /// 生成规则：默认收起的可展开区块（长段规则不占首屏）。
  Widget _buildRulesSection() {
    return ExpandableSection(
      key: const Key('rules-section'),
      title: '生成规则',
      subtitle: '两档模式、并发、重试与库存规则',
      child: Text(
        generationRulesText,
        style: const TextStyle(
          fontSize: 12,
          color: AppColors.textMuted,
          height: 1.6,
        ),
      ),
    );
  }

  /// 进行中摘要：一行「进行中 N 项」+「查看」，点击进入作品页进行中分段。
  Widget _buildRunningSummary(AppState app) {
    return Container(
      key: const Key('running-summary'),
      padding: const EdgeInsets.only(left: 12, right: 4, top: 4, bottom: 4),
      decoration: BoxDecoration(
        color: AppColors.yellowSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: AppColors.yellowDeep.withValues(alpha: 0.30),
        ),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '进行中 ${app.runningCount} 项',
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          TextButton(
            onPressed: () => gotoMainTab(context, 1),
            child: const Text('查看'),
          ),
        ],
      ),
    );
  }

  /// 最近的作品：最多 3 个已完成作品；加载中 / 加载失败可重试 / 空列表三态。
  Widget _buildRecentWorks(AppState app) {
    final recent = app.recentDoneSummaries;
    return Column(
      key: const Key('recent-works'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Padding(
          padding: EdgeInsets.only(bottom: 8),
          child: Text(
            '最近的作品',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
          ),
        ),
        if (app.recentDoneLoading && recent.isEmpty)
          const LoadingBlock(text: '正在加载最近作品……', height: 96)
        else if (app.recentDoneError != null && recent.isEmpty)
          InfoBanner(
            icon: '⚠️',
            tone: 'bad',
            title: '最近作品加载失败',
            text: app.recentDoneError!,
            action: OutlinedButton(
              onPressed: () => app.refreshRecentDone(),
              child: const Text('重试'),
            ),
          )
        else if (recent.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 10),
            child: Text(
              '还没有完成的作品。生成第一件作品后，这里会显示最近 3 个作品。',
              style: TextStyle(fontSize: 12, color: AppColors.textMuted),
            ),
          )
        else
          for (final job in recent) _RecentWorkCard(job: job),
      ],
    );
  }

  /// 底部固定主按钮：全宽「生成作品」，提交中禁用并显示「启动中…」。
  Widget _buildStartButton() {
    return SizedBox(
      width: double.infinity,
      child: FilledButton(
        key: const Key('start-build-button'),
        onPressed: _submitting ? null : _start,
        child: Text(_submitting ? '启动中…' : '生成作品'),
      ),
    );
  }
}

/// 最近作品卡片：整卡单一跳转到该任务的默认落点，不提供多个同级按钮。
class _RecentWorkCard extends StatelessWidget {
  const _RecentWorkCard({required this.job});

  final JobSummary job;

  @override
  Widget build(BuildContext context) {
    final spec = job.specText.isEmpty ? '规格未记录' : job.specText;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: AppCard(
        onTap: () => unawaited(openJobById(context, job.id)),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    shortDesc(job.displayName, 32),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    spec,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 11.5,
                      color: AppColors.textMuted,
                    ),
                  ),
                ],
              ),
            ),
            const Icon(
              Icons.chevron_right,
              size: 18,
              color: AppColors.textDim,
            ),
          ],
        ),
      ),
    );
  }
}
