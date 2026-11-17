// 服务连接表单：地址 / 令牌 / 测试连接 / 保存，展示真实健康检查、零件目录与鉴权结果。
// 首次引导与设置页共用；错误信息含 code / requestId，便于与服务端日志关联。
import 'package:flutter/material.dart';

import '../../core/service_address.dart';
import '../../core/theme.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';

/// 服务连接表单。
class ServiceForm extends StatefulWidget {
  const ServiceForm({
    super.key,
    required this.initialUrl,
    required this.initialToken,
    required this.onSave,
    required this.saveLabel,
    this.onTestConnection,
    this.firstRun = false,
  });

  final String initialUrl;
  final String initialToken;

  /// 保存回调：返回真实连接检查结果（用于展示）。
  final Future<ConnectionCheck> Function(String url, String token) onSave;

  /// 仅测试连接（不保存）；为空时使用 onSave 前先测试的逻辑。
  final Future<ConnectionCheck> Function(String url, String token)? onTestConnection;

  final String saveLabel;
  final bool firstRun;

  @override
  State<ServiceForm> createState() => _ServiceFormState();
}

class _ServiceFormState extends State<ServiceForm> {
  late final TextEditingController _urlCtrl =
      TextEditingController(text: widget.initialUrl);
  late final TextEditingController _tokenCtrl =
      TextEditingController(text: widget.initialToken);
  bool _obscure = true;
  bool _busy = false;
  String? _localError;
  ConnectionCheck? _check;

  @override
  void dispose() {
    _urlCtrl.dispose();
    _tokenCtrl.dispose();
    super.dispose();
  }

  /// 提交前校验：地址格式 + 非回环服务的令牌要求（不静默改写地址）。
  String? _validate() {
    final parsed = ServiceAddress.parse(_urlCtrl.text);
    if (!parsed.ok) return parsed.error;
    final tokenError =
        parsed.address!.tokenRequirementError(hasToken: _tokenCtrl.text.trim().isNotEmpty);
    if (tokenError != null) return tokenError;
    return null;
  }

  Future<void> _test() async {
    final error = _validate();
    if (error != null) {
      setState(() => _localError = error);
      return;
    }
    setState(() {
      _localError = null;
      _busy = true;
      _check = null;
    });
    try {
      final tester = widget.onTestConnection;
      final check = tester != null
          ? await tester(_urlCtrl.text, _tokenCtrl.text)
          : await widget.onSave(_urlCtrl.text, _tokenCtrl.text);
      if (!mounted) return;
      setState(() => _check = check);
    } catch (e) {
      if (!mounted) return;
      setState(() => _localError = '连接测试失败：${describeError(e)}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    final error = _validate();
    if (error != null) {
      setState(() => _localError = error);
      return;
    }
    setState(() {
      _localError = null;
      _busy = true;
    });
    try {
      final check = await widget.onSave(_urlCtrl.text, _tokenCtrl.text);
      if (!mounted) return;
      setState(() => _check = check);
    } catch (e) {
      if (!mounted) return;
      setState(() => _localError = '保存失败：${describeError(e)}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          key: const Key('service-url-field'),
          controller: _urlCtrl,
          keyboardType: TextInputType.url,
          autocorrect: false,
          enableSuggestions: false,
          textInputAction: TextInputAction.next,
          decoration: InputDecoration(
            labelText: '服务地址',
            hintText: '<电脑局域网 IP>:8600 或 https://example.com',
            helperText: '支持主机、端口与 http/https；未写协议时按 http:// 处理。',
            helperMaxLines: 2,
            errorMaxLines: 3,
            prefixIcon: const Icon(Icons.dns_outlined),
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          key: const Key('service-token-field'),
          controller: _tokenCtrl,
          obscureText: _obscure,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(
            labelText: '访问令牌（非回环服务必填）',
            hintText: 'Authorization: Bearer <token>',
            helperText: '令牌只保存在系统安全存储；不会写进日志、截图或 URL。',
            helperMaxLines: 2,
            prefixIcon: const Icon(Icons.key_outlined),
            suffixIcon: IconButton(
              tooltip: _obscure ? '显示令牌' : '隐藏令牌',
              icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility),
              onPressed: () => setState(() => _obscure = !_obscure),
            ),
          ),
        ),
        if (_localError != null) ...[
          const SizedBox(height: 12),
          InfoBanner(text: _localError!, icon: '⚠️', tone: 'bad'),
        ],
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _busy ? null : _test,
                icon: const Icon(Icons.wifi_tethering, size: 18),
                label: const Text('测试连接'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: FilledButton.icon(
                key: const Key('service-save-button'),
                onPressed: _busy ? null : _save,
                icon: _busy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.check, size: 18),
                label: Text(widget.saveLabel),
              ),
            ),
          ],
        ),
        if (_check != null) ...[
          const SizedBox(height: 14),
          _ConnectionResult(check: _check!),
        ],
      ],
    );
  }
}

class _ConnectionResult extends StatelessWidget {
  const _ConnectionResult({required this.check});

  final ConnectionCheck check;

  @override
  Widget build(BuildContext context) {
    final ok = check.ok;
    final tone = ok ? 'ok' : (check.healthOk ? 'warn' : 'bad');
    final lines = <Widget>[];
    lines.add(_row('服务健康', check.healthOk ? '通过（${check.status}）' : '失败',
        check.healthOk ? AppColors.ok : AppColors.danger));
    lines.add(_row('API 版本', 'v${check.apiVersion}（需要 v1）',
        check.apiVersionCompatible ? AppColors.ok : AppColors.danger));
    if (check.healthOk) lines.add(_row('健康接口延迟', '${check.latencyMs}ms', AppColors.text));
    if (check.checkedParts) {
      lines.add(_row('零件目录', '${check.partsCount ?? 0} 个「形状×颜色」变体',
          (check.partsCount ?? 0) > 0 ? AppColors.ok : AppColors.warn));
    }
    if (check.authChecked) {
      lines.add(_row('任务接口鉴权', check.authOk ? '通过' : '失败（${check.authError ?? '未知'}）',
          check.authOk ? AppColors.ok : AppColors.danger));
    } else {
      lines.add(_row('任务接口鉴权', '未检查（回环服务可不配置令牌）', AppColors.textMuted));
    }
    if (check.error != null) {
      lines.add(_row('错误', check.error!, AppColors.danger));
    }
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.tone(tone).withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.tone(tone).withValues(alpha: 0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(ok ? Icons.check_circle : Icons.error_outline,
                  color: AppColors.tone(tone), size: 18),
              const SizedBox(width: 6),
              Text(ok ? '连接检查通过' : '连接检查未通过',
                  style: TextStyle(
                      color: AppColors.tone(tone), fontWeight: FontWeight.w700)),
              if (check.requestId != null) ...[
                const Spacer(),
                Text('requestId ${check.requestId}',
                    style: const TextStyle(fontSize: 10, color: AppColors.textDim)),
              ],
            ],
          ),
          const SizedBox(height: 8),
          ...lines,
        ],
      ),
    );
  }

  Widget _row(String label, String value, Color color) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 96,
            child: Text(label,
                style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
          ),
          Expanded(
            child: Text(value, style: TextStyle(fontSize: 12, color: color)),
          ),
        ],
      ),
    );
  }
}
