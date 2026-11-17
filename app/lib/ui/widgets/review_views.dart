// 评审渲染图展示：正视/侧视/俯视/轴测（以及评审拼图），点击查看大图并支持缩放。
// 没有图片时要区分「快速未渲染」与「加载失败」，加载失败可单独重试（局部错误，不影响整页）。
import 'package:flutter/material.dart';

import '../../core/theme.dart';

/// 图片视图标签顺序。
const List<List<String>> reviewViewOrder = [
  ['front', '正视'],
  ['side', '侧视'],
  ['top', '俯视'],
  ['iso', '轴测'],
  ['sheet', '评审拼图'],
];

/// 评审图条：两列网格 + 点击大图。
class ReviewViewsGrid extends StatelessWidget {
  const ReviewViewsGrid({
    super.key,
    required this.views,
    required this.urlOf,
    required this.headers,
    this.emptyText = '评审图还没有，或这次运行没有渲染。',
  });

  /// key（front/side/top/iso/sheet）→ 服务端相对路径或绝对 URL。
  final Map<String, String> views;
  final String Function(String pathOrUrl) urlOf;
  final Map<String, String> headers;

  /// 没有图片时的说明（页面负责区分「快速未渲染」与「加载失败」）。
  final String emptyText;

  @override
  Widget build(BuildContext context) {
    final items = <Widget>[];
    for (final item in reviewViewOrder) {
      final path = views[item[0]];
      if (path == null || path.isEmpty) continue;
      items.add(_ReviewImageTile(
        label: item[1],
        url: urlOf(path),
        headers: headers,
      ));
    }
    if (items.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Text(emptyText,
            style: const TextStyle(color: AppColors.textMuted, height: 1.5)),
      );
    }
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 10,
      crossAxisSpacing: 10,
      childAspectRatio: 1.05,
      children: items,
    );
  }
}

class _ReviewImageTile extends StatefulWidget {
  const _ReviewImageTile({required this.label, required this.url, required this.headers});

  final String label;
  final String url;
  final Map<String, String> headers;

  @override
  State<_ReviewImageTile> createState() => _ReviewImageTileState();
}

class _ReviewImageTileState extends State<_ReviewImageTile> {
  int _attempt = 0;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '评审图 ${widget.label}，点击查看大图',
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () {
          Navigator.of(context).push(MaterialPageRoute<void>(
            builder: (_) => FullScreenImageViewer(
              title: widget.label,
              url: widget.url,
              headers: widget.headers,
            ),
          ));
        },
        child: Container(
          decoration: BoxDecoration(
            color: AppColors.bgElevated,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.borderSoft),
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            children: [
              Expanded(
                child: Image.network(
                  widget.url,
                  key: ValueKey('${widget.url}#$_attempt'),
                  headers: widget.headers,
                  fit: BoxFit.contain,
                  loadingBuilder: (context, child, progress) {
                    if (progress == null) return child;
                    return const Center(
                      child: SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    );
                  },
                  errorBuilder: (context, error, stack) => Center(
                    child: Padding(
                      padding: const EdgeInsets.all(8),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Text('图片加载失败',
                              style: TextStyle(color: AppColors.danger, fontSize: 12)),
                          const SizedBox(height: 6),
                          OutlinedButton(
                            onPressed: () => setState(() => _attempt++),
                            child: const Text('重试', style: TextStyle(fontSize: 12)),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 6),
                color: AppColors.surface,
                child: Text(
                  widget.label,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 全屏图片查看：支持系统缩放/平移。
class FullScreenImageViewer extends StatelessWidget {
  const FullScreenImageViewer({
    super.key,
    required this.title,
    required this.url,
    required this.headers,
  });

  final String title;
  final String url;
  final Map<String, String> headers;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        title: Text(title),
      ),
      body: InteractiveViewer(
        minScale: 1,
        maxScale: 6,
        child: Center(
          child: Image.network(
            url,
            headers: headers,
            fit: BoxFit.contain,
            errorBuilder: (context, error, stack) => const Text(
              '评审图加载失败，请返回后重试',
              style: TextStyle(color: AppColors.danger),
            ),
          ),
        ),
      ),
    );
  }
}
