// 生成进度页的设计稿主视觉：真实设计稿产生后显示可交互 3D 场景，
// 换稿（stamp 变化）才重建场景，并用 keepCamera 保留用户已调整的视角；
// 设计稿尚未产生时使用紧凑空态（高度 ≤120dp），不用大面积空白画布挤占阶段与进度信息。
import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../models/design.dart';
import '../../three_d/lego_3d_view.dart';
import '../../three_d/lego_camera.dart';
import '../../three_d/lego_scene.dart';

/// 设计稿主视觉区（页面用 Key('progress-design') 挂载）。
class ProgressDesignSection extends StatefulWidget {
  const ProgressDesignSection({super.key, required this.design});

  /// 任务快照中的实时设计稿；为空或空稿时显示紧凑空态。
  final DesignDraft? design;

  @override
  State<ProgressDesignSection> createState() => _ProgressDesignSectionState();
}

class _ProgressDesignSectionState extends State<ProgressDesignSection> {
  /// 页面自持有的 3D 控制器（换稿时保留相机）。
  final Lego3DController _controller = Lego3DController();

  /// 已渲染设计稿的内容哈希（stamp）。
  String _stamp = '';

  /// 是否已经挂载过场景（决定换稿时是否保留相机）。
  bool _attached = false;

  @override
  void initState() {
    super.initState();
    _syncDesignScene();
  }

  @override
  void didUpdateWidget(covariant ProgressDesignSection oldWidget) {
    super.didUpdateWidget(oldWidget);
    _syncDesignScene();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// 只有 stamp 变化才重建场景；keepCamera 让用户手动调整的视角不被轮询重置。
  void _syncDesignScene() {
    final design = widget.design;
    if (design == null || design.isEmpty) return;
    if (design.stamp == _stamp && _controller.scene != null) return;
    _stamp = design.stamp;
    _controller.attachScene(
      LegoSceneBuilder.design(draft: design),
      keepCamera: _attached,
    );
    _attached = true;
  }

  @override
  Widget build(BuildContext context) {
    final design = widget.design;
    if (design == null || design.isEmpty) {
      return Container(
        height: 96,
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: AppColors.surfaceHigh,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.borderSoft),
        ),
        child: const Text(
          '造型完成后，彩色设计稿会出现在这里。',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 12, color: AppColors.textMuted),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          height: 260,
          decoration: BoxDecoration(
            color: AppColors.bg,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.borderSoft),
          ),
          clipBehavior: Clip.antiAlias,
          child: Lego3DView(
            controller: _controller,
            semanticsLabel: '实时彩色设计稿：可单指旋转、双指缩放平移',
          ),
        ),
        Row(
          children: [
            const Expanded(
              child: Text(
                '彩色设计稿（服务端实时）· 单指旋转 · 双指缩放/平移',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 11, color: AppColors.textMuted),
              ),
            ),
            TextButton.icon(
              onPressed: _controller.resetView,
              icon: const Icon(Icons.center_focus_strong, size: 14),
              label: const Text('重置视角', style: TextStyle(fontSize: 11)),
            ),
          ],
        ),
      ],
    );
  }
}
