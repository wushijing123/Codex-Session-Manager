from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from demo_dashboard import ACTIVE_ID, ARCHIVED_ID, create_demo_fixture
from lib.core import collect_log_files, conversation_preview, discover_database, rollout_head, search_conversation_text
from lib.server import DashboardState


class HistoryCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = create_demo_fixture(self.root)
        self.state = DashboardState(self.fixture['codex_home'], self.fixture['app_dir'], ROOT / 'assets/dashboard', self.fixture['pinned_file'], False)
        self.tools = self.state.tools

    def tearDown(self):
        self.temp.cleanup()

    def compress(self, path):
        if not shutil.which('zstd'):
            self.skipTest('zstd command not installed')
        subprocess.run(['zstd', '-q', '--', str(path)], check=True)
        return Path(str(path) + '.zst')

    def remove_session(self, session_id):
        path = self.tools.log_path(self.tools.record(session_id))
        path.unlink()
        with contextlib.closing(sqlite3.connect(self.state.codex_home / 'state_5.sqlite')) as conn, conn:
            conn.execute('DELETE FROM threads WHERE id=?', (session_id,))
        self.state.refresh()

    def test_compressed_sibling_is_readable_when_sqlite_points_to_plain_log(self):
        path = self.tools.log_path(self.tools.record(ARCHIVED_ID))
        compressed = self.compress(path)
        path.unlink()
        self.state.refresh()
        record = self.tools.record(ARCHIVED_ID)
        self.assertEqual('archived', record['actual_state'])
        self.assertTrue(record['rollout_path'].endswith('.jsonl.zst'))
        self.assertTrue(self.state.session_detail(ARCHIVED_ID, 20, 0)['available'])
        self.assertEqual(2, self.state.session_detail(ARCHIVED_ID, 20, 0)['total_messages'])
        self.assertIn(ARCHIVED_ID, collect_log_files(self.state.codex_home))

    def test_plain_and_compressed_copies_are_one_session_not_a_false_conflict(self):
        path = self.tools.log_path(self.tools.record(ARCHIVED_ID))
        self.compress(path)
        self.state.refresh()
        rows = [row for row in self.state.catalog['sessions'] if row['id'] == ARCHIVED_ID]
        self.assertEqual(1, len(rows))
        self.assertFalse(rows[0]['state_conflict'])

    def test_orphan_compressed_log_appears_with_project_and_searchable_body(self):
        path = self.tools.log_path(self.tools.record(ACTIVE_ID))
        self.compress(path)
        path.unlink()
        with contextlib.closing(sqlite3.connect(self.state.codex_home / 'state_5.sqlite')) as conn, conn:
            conn.execute('DELETE FROM threads WHERE id=?', (ACTIVE_ID,))
        self.state.refresh()
        self.assertEqual('unindexed', self.tools.record(ACTIVE_ID)['actual_state'])
        self.assertTrue(self.tools.record(ACTIVE_ID)['first_user_message'])
        result = self.state._search_archived_content('launch checklist', 200, self.state.catalog['sessions'], include_active=True)
        self.assertIn(ACTIVE_ID, [match['session_id'] for match in result['matches']])
        backup = self.tools.action(ACTIVE_ID, 'backup')['backup']
        self.assertTrue((self.state.app_dir / 'backups' / backup['filename']).exists())

    def test_paginated_item_messages_are_complete_and_not_duplicated(self):
        path = self.root / 'paginated.jsonl'
        events = [
            {'type':'event_msg','payload':{'type':'task_started','turn_id':'t1'}},
            {'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':'重复的真实用户需求'}]}},
            {'type':'event_msg','payload':{'type':'item_completed','turn_id':'t1','item':{'type':'UserMessage','id':'u1','content':[{'type':'Text','text':'重复的真实用户需求'}]}}},
            {'type':'event_msg','payload':{'type':'item_completed','turn_id':'t1','item':{'type':'AgentMessage','phase':'commentary','content':[{'text':'进度不应显示'}]}}},
            {'type':'event_msg','payload':{'type':'item_completed','turn_id':'t1','item':{'type':'AgentMessage','phase':'final_answer','content':[{'text':'完整最终回复，含海盐关键词'}]}}},
            {'type':'response_item','payload':{'type':'message','role':'assistant','phase':'final_answer','content':[{'text':'完整最终回复，含海盐关键词'}]}},
        ]
        path.write_text('\n'.join(json.dumps(event, ensure_ascii=True) for event in events))
        result = conversation_preview(path, offset=0)
        self.assertEqual(['user','assistant'], [message['role'] for message in result['messages']])
        self.assertEqual('完整最终回复，含海盐关键词', result['messages'][1]['text'])
        self.assertTrue(search_conversation_text(path, '海盐'))
        compressed = self.compress(path)
        self.assertTrue(search_conversation_text(compressed, '海盐'))
        self.assertEqual(2, conversation_preview(compressed, offset=0)['total_messages'])

    def test_injected_plugin_agents_and_skill_context_is_not_chat(self):
        path = self.root / 'injected-context.jsonl'
        def response(text):
            return {'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':text}]}}
        context = ('<recommended_plugins>\nPluginContextOnly\n</recommended_plugins>\n'
                   '# AGENTS.md instructions for /demo/project\n\n<INSTRUCTIONS>\nProject rules\n</INSTRUCTIONS>\n'
                   '<environment_context><cwd>/demo/project</cwd></environment_context>')
        events = [response(context), response('<skill>\n<name>demo</name>\n<path>/demo/SKILL.md</path>\nLoaded skill instructions\n</skill>')]
        for index in range(23):
            text = f'真实请求 {index}'
            events.extend([response(text), {'type':'event_msg','payload':{'type':'user_message','message':text}}])
        path.write_text('\n'.join(json.dumps(event) for event in events))
        first = conversation_preview(path, offset=0, max_messages=20)
        second = conversation_preview(path, offset=first['next_offset'], max_messages=20)
        self.assertEqual(23, first['total_messages'])
        self.assertEqual([f'真实请求 {index}' for index in range(23)], [message['text'] for message in first['messages'] + second['messages']])
        self.assertFalse(search_conversation_text(path, 'PluginContextOnly'))
        self.assertTrue(search_conversation_text(path, '真实请求'))
        self.assertEqual('真实请求 0', rollout_head(path)['first_user_message'])

    def test_canonical_messages_strip_only_leading_context_and_keep_request(self):
        path = self.root / 'canonical-context.jsonl'
        texts = [
            '<recommended_plugins>PluginContextOnly</recommended_plugins>',
            '<skills_instructions>Loaded skill list</skills_instructions>\n<in-app-browser-context>Browser context</in-app-browser-context>\n## My request:\n请整理这段对话',
            '请解释下面这个标签：\n<recommended_plugins>这是我写的示例</recommended_plugins>',
            '```xml\n<environment_context>用户代码示例</environment_context>\n```',
            '请保留我的标题\n## My request for Codex:\n这是正文的一部分',
        ]
        path.write_text('\n'.join(json.dumps({'type':'event_msg','payload':{'type':'item_completed','item':{'type':'UserMessage','content':[{'type':'Text','text':text}]}}}) for text in texts))
        messages = conversation_preview(path, offset=0)['messages']
        self.assertEqual(4, len(messages))
        self.assertEqual('请整理这段对话', messages[0]['text'])
        self.assertEqual(texts[2:], [message['text'] for message in messages[1:]])

    def test_mixed_legacy_and_paginated_history_keeps_both_eras(self):
        path = self.root/'mixed.jsonl'
        events = [
            {'type':'turn_context','payload':{'turn_id':'old'}},
            {'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':'old user'}]}},
            {'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'text':'old answer'}]}},
            {'type':'event_msg','payload':{'type':'item_completed','turn_id':'new','item':{'type':'UserMessage','content':[{'text':'new user'}]}}},
            {'type':'event_msg','payload':{'type':'item_completed','turn_id':'new','item':{'type':'AgentMessage','phase':'final_answer','content':[{'text':'new answer'}]}}},
        ]
        path.write_text('\n'.join(json.dumps(e) for e in events))
        self.assertEqual(['old user','old answer','new user','new answer'],[m['text'] for m in conversation_preview(path,offset=0)['messages']])

    def test_legacy_assistant_messages_without_phase_are_visible(self):
        path = self.root / 'legacy.jsonl'
        path.write_text(json.dumps({'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'text':'Legacy final reply'}]}}))
        self.assertEqual('Legacy final reply', conversation_preview(path)['messages'][0]['text'])

    def test_compressed_backup_keeps_original_compressed_bytes(self):
        path = self.tools.log_path(self.tools.record(ARCHIVED_ID))
        compressed = self.compress(path)
        path.unlink()
        original = compressed.read_bytes()
        self.state.refresh()
        backup = self.tools.action(ARCHIVED_ID, 'backup')['backup']
        with zipfile.ZipFile(self.state.app_dir / 'backups' / backup['filename']) as bundle:
            self.assertEqual(original, bundle.read('session.jsonl.zst'))
            metadata = json.loads(bundle.read('backup.json'))
        self.assertEqual(hashlib.sha256(original).hexdigest(), metadata['sha256'])

    @mock.patch('lib.session_tools.shutil.which', return_value='/fake/codex')
    def test_restore_is_non_overwriting_and_rejects_modified_backup(self, _which):
        backup = self.tools.action(ACTIVE_ID,'backup')['backup']
        with mock.patch('lib.session_tools.native_request') as native:
            with self.assertRaisesRegex(PermissionError,'restore_session_exists'):
                self.tools.restore_backup(backup['filename'])
            native.assert_not_called()
        path = self.state.app_dir / 'backups' / backup['filename']
        with zipfile.ZipFile(path) as bundle:
            metadata = bundle.read('backup.json')
        self.remove_session(ACTIVE_ID)
        with zipfile.ZipFile(path,'w') as bundle:
            bundle.writestr('backup.json',metadata)
            bundle.writestr('session.jsonl',b'corrupted')
        with mock.patch('lib.session_tools.native_request') as native:
            with self.assertRaisesRegex(ValueError,'backup_hash_mismatch'):
                self.tools.restore_backup(backup['filename'])
            native.assert_not_called()
        self.assertFalse(any(ACTIVE_ID in p.name for p in self.state.codex_home.rglob('*.jsonl')))

    def test_restore_via_native_index_keeps_original_id_and_bytes(self):
        record = self.tools.record(ACTIVE_ID)
        original = self.tools.log_path(record).read_bytes()
        backup = self.tools.action(ACTIVE_ID,'backup')['backup']
        with zipfile.ZipFile(self.state.app_dir / 'backups' / backup['filename']) as bundle:
            snapshot = json.loads(bundle.read('backup.json'))['database_rows']['thread']
        self.remove_session(ACTIVE_ID)
        def native(binary, home, method, params):
            self.assertEqual(ACTIVE_ID,params['threadId'])
            if method=='thread/read':
                source = next((home/'sessions').rglob(f'*{ACTIVE_ID}.jsonl'))
                snapshot['rollout_path']=str(source)
                with contextlib.closing(sqlite3.connect(home/'state_5.sqlite')) as conn, conn:
                    keys=list(snapshot)
                    conn.execute(f'INSERT INTO threads ({",".join(keys)}) VALUES ({",".join("?" for _ in keys)})',[snapshot[k] for k in keys])
                return {'thread':{'id':ACTIVE_ID}}
            return {}
        with mock.patch('lib.session_tools.native_request',side_effect=native),mock.patch('lib.session_tools.shutil.which',return_value='/fake/codex'):
            result=self.tools.restore_backup(backup['filename'])
        self.assertTrue(result['verified'])
        self.assertEqual(original,self.tools.log_path(self.tools.record(ACTIVE_ID)).read_bytes())
        self.assertFalse(self.tools.list_backups()[0]['can_restore'])

    def test_configured_sqlite_home_takes_precedence_over_env(self):
        configured=self.root/'configured';configured.mkdir()
        shutil.copyfile(self.state.codex_home/'state_5.sqlite',configured/'state_5.sqlite')
        (self.state.codex_home/'config.toml').write_text('sqlite_home = '+json.dumps(str(configured)))
        with mock.patch.dict(os.environ,{'CODEX_SQLITE_HOME':str(self.root/'wrong')}):
            _,selected,_=discover_database(self.state.codex_home,set())
        self.assertEqual((configured/'state_5.sqlite').resolve(),Path(selected))

    def test_backup_names_are_confined_to_backup_directory(self):
        with self.assertRaisesRegex(ValueError,'invalid_backup'):
            self.tools.backup_path('../outside.zip')


if __name__=='__main__':
    unittest.main()
