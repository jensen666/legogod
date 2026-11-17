// 本地存储测试：只保存地址/草稿/缓存/界面状态，令牌只走安全存储（测试环境无插件时容错），
// 切换服务必须清空该服务缓存。
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  test('保存服务地址与草稿、最近任务、历史查询、界面状态', () async {
    final storage = AppStorage();
    await storage.init();
    await storage.saveBaseUrl('https://example.com:8600');
    await storage.saveDraft(desc: '一只小狗', mode: 'fidelity');
    await storage.saveRecentJobIds(['a', 'b', 'c', 'd', 'e', 'f']);
    await storage.saveHistoryQuery(
        const HistoryQueryState(q: '狗', status: 'done', outcome: 'fast_success', page: 2));
    await storage.saveUiState({
      'detailTabs': {'job1': 'review'},
      'studio': {
        'job1': {'tab': 'build', 'step': 7}
      },
    });

    final second = AppStorage();
    await second.init();
    expect(second.baseUrl, 'https://example.com:8600');
    expect(second.draft!['desc'], '一只小狗');
    expect(second.draft!['mode'], 'fidelity');
    // 最近查看最多保留 5 个
    expect(second.recentJobIds, ['a', 'b', 'c', 'd', 'e']);
    final query = second.historyQuery;
    expect(query.q, '狗');
    expect(query.status, 'done');
    expect(query.outcome, 'fast_success');
    expect(query.page, 2);
    final ui = second.uiState;
    expect((ui['detailTabs'] as Map)['job1'], 'review');
    expect((ui['studio'] as Map)['job1']['step'], 7);
  });

  test('任务详情缓存只保留最近 3 个', () async {
    final storage = AppStorage();
    await storage.init();
    for (final id in ['j1', 'j2', 'j3', 'j4']) {
      await storage.saveCachedJobDetail(id, {'id': id, 'status': 'done'});
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
    final cached = storage.cachedDetails;
    expect(cached.length, 3);
    expect(cached.containsKey('j1'), isFalse);
    expect(cached.containsKey('j4'), isTrue);
  });

  test('切换服务清空缓存但保留草稿', () async {
    final storage = AppStorage();
    await storage.init();
    await storage.saveBaseUrl('http://old:8600');
    await storage.saveCachedServiceKey('http://old:8600');
    await storage.saveDraft(desc: '保留我', mode: 'fast');
    await storage.saveCachedParts({
      'parts': [
        {'id': 'B1x1', 'count': 1}
      ]
    });
    await storage.saveCachedHistory({'jobs': [], 'total': 0});
    await storage.saveSelectedJobId('job1');
    await storage.saveRecentJobIds(['job1']);

    await storage.clearServiceCaches();

    expect(storage.cachedParts, isNull);
    expect(storage.cachedHistory, isNull);
    expect(storage.selectedJobId, isNull);
    expect(storage.recentJobIds, isEmpty);
    expect(storage.cachedServiceKey, isNull);
    // 草稿是用户内容，不随服务切换清空
    expect(storage.draft!['desc'], '保留我');
  });

  test('安全存储不可用时不崩溃且不回退明文', () async {
    final storage = AppStorage();
    await storage.init();
    // 测试环境没有平台插件：读取应返回 null，写入返回 false，且不抛异常。
    final token = await storage.readToken();
    expect(token, isNull);
    final saved = await storage.saveToken('secret');
    expect(saved, isFalse);
  });

  test('损坏的缓存 JSON 被忽略而不是崩溃', () async {
    SharedPreferences.setMockInitialValues(<String, Object>{
      'legogod.v1.draft': '{not json',
      'legogod.v1.uiState': '[]',
    });
    final storage = AppStorage();
    await storage.init();
    expect(storage.draft, isNull);
    expect(storage.uiState, isEmpty);
  });
}
