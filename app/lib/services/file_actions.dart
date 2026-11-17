// 文件操作：系统分享面板、系统文件选择器保存、系统浏览器打开。
// 使用系统能力，不依赖桌面下载目录；
// 失败或用户取消时给出真实结果，绝不生成空文件冒充成功。
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

/// 文件操作结果。
class FileActionResult {
  const FileActionResult({
    required this.ok,
    required this.message,
    this.cancelled = false,
    this.path,
  });

  final bool ok;
  final String message;

  /// 用户主动取消（选择器/分享取消）：不算错误，但也不是成功。
  final bool cancelled;
  final String? path;
}

/// 文件操作门面。
class FileActions {
  FileActions._();

  /// 常见产物 MIME。
  static String mimeOf(String fileName) {
    final lower = fileName.toLowerCase();
    if (lower.endsWith('.md')) return 'text/markdown';
    if (lower.endsWith('.json')) return 'application/json';
    if (lower.endsWith('.html')) return 'text/html';
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.txt')) return 'text/plain';
    return 'application/octet-stream';
  }

  /// 写入缓存目录（分享/预览用临时文件）。
  static Future<File> writeTemp({required String fileName, required List<int> bytes}) async {
    final dir = await getTemporaryDirectory();
    final safeName = fileName.replaceAll(RegExp(r'[\\/:*?"<>|]+'), '_');
    final file = File('${dir.path}/$safeName');
    await file.writeAsBytes(bytes, flush: true);
    return file;
  }

  /// 调起系统分享面板（文件来自真实服务端字节）。
  static Future<FileActionResult> shareArtifact({
    required String fileName,
    required List<int> bytes,
    String? text,
  }) async {
    try {
      if (bytes.isEmpty) {
        return const FileActionResult(ok: false, message: '文件内容为空，已取消分享');
      }
      final file = await writeTemp(fileName: fileName, bytes: bytes);
      final result = await SharePlus.instance.share(ShareParams(
        files: [XFile(file.path, mimeType: mimeOf(fileName))],
        subject: fileName,
        text: text,
      ));
      final status = result.status;
      if (status == ShareResultStatus.dismissed) {
        return FileActionResult(
          ok: false,
          cancelled: true,
          message: '已取消分享',
          path: file.path,
        );
      }
      return FileActionResult(ok: true, message: '已打开系统分享面板', path: file.path);
    } catch (e) {
      debugPrint('[file] 分享失败：$e');
      return FileActionResult(ok: false, message: '分享失败：${_reason(e)}');
    }
  }

  /// 通过系统文件选择器保存到用户选择的位置（Android SAF）。
  static Future<FileActionResult> saveArtifact({
    required String fileName,
    required List<int> bytes,
    String? mime,
  }) async {
    try {
      if (bytes.isEmpty) {
        return const FileActionResult(ok: false, message: '文件内容为空，未保存');
      }
      final uri = await FilePicker.saveFile(
        fileName: fileName,
        bytes: Uint8List.fromList(bytes),
        mimeType: mime ?? mimeOf(fileName),
        dialogTitle: '保存 $fileName',
      );
      if (uri == null) {
        return const FileActionResult(ok: false, cancelled: true, message: '已取消保存');
      }
      return FileActionResult(ok: true, message: '已保存到所选位置', path: uri.toString());
    } catch (e) {
      debugPrint('[file] 保存失败：$e');
      return FileActionResult(ok: false, message: '保存失败：${_reason(e)}');
    }
  }

  /// 用系统浏览器打开独立 3D 页等外部地址（说明去向由页面负责）。
  static Future<FileActionResult> openExternal(String url) async {
    final uri = Uri.tryParse(url);
    if (uri == null || !(uri.scheme == 'http' || uri.scheme == 'https')) {
      return const FileActionResult(ok: false, message: '链接不合法，无法打开');
    }
    try {
      final launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!launched) {
        return const FileActionResult(ok: false, message: '系统没有可打开该链接的应用');
      }
      return const FileActionResult(ok: true, message: '已在系统浏览器打开');
    } catch (e) {
      debugPrint('[file] 打开外部链接失败：$e');
      return FileActionResult(ok: false, message: '打开失败：${_reason(e)}');
    }
  }

  static String _reason(Object error) {
    final text = error.toString();
    return text.replaceFirst('Exception: ', '');
  }
}
