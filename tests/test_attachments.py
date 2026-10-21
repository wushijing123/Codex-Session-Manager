from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import http.cookiejar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from demo_dashboard import ACTIVE_ID, create_demo_fixture
from lib.attachments import ImageStore, extract_images
from lib.core import conversation_preview
from lib.server import DashboardState, DashboardServer

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=')
URI = 'data:image/png;base64,' + base64.b64encode(PNG).decode()


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ImageStore()

    def tearDown(self):
        self.temp.cleanup()

    def test_embedded_original_survives_missing_file_and_duplicate_event(self):
        missing = self.root / 'gone.png'
        text = f'# Files mentioned by the user:\n\n## gone.png: {missing}\n\n## My request for Codex:\n替换人物'
        events = [
            {'type':'event_msg','payload':{'type':'task_started','turn_id':'t1'}},
            {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':text + f'\n<image name=[Image #1] path="{missing}">\n</image>'},{'type':'input_image','image_url':URI}]}},
            {'type':'event_msg','payload':{'type':'user_message','message':text,'images':[{'type':'local_image','path':str(missing)}]}},
        ]
        log = self.root / 'history.jsonl'
        log.write_text('\n'.join(json.dumps(event) for event in events))
        preview = conversation_preview(log, offset=0, image_resolver=lambda ref:self.store.render(ref,str(self.root),[1024]))
        self.assertEqual(1, preview['total_messages'])
        self.assertEqual('替换人物', preview['messages'][0]['text'])
        image = preview['messages'][0]['images'][0]
        self.assertEqual('available', image['status'])
        self.assertEqual(('image/png', PNG), self.store.get(image['url'].split('=')[-1]))
        self.assertNotIn('base64,', json.dumps(preview))
        self.assertNotIn('base64,', json.dumps(conversation_preview(log,offset=0)))

    def test_image_only_message_is_kept(self):
        log = self.root / 'image-only.jsonl'
        log.write_text(json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_image','image_url':URI}]}}))
        preview = conversation_preview(log,offset=0,image_resolver=lambda ref:self.store.render(ref,str(self.root),[1024]))
        self.assertEqual(1,preview['total_messages'])
        self.assertEqual('',preview['messages'][0]['text'])
        self.assertEqual('available',preview['messages'][0]['images'][0]['status'])

    def test_local_images_resolve_but_remote_svg_and_secrets_are_not_served(self):
        (self.root/'photo.png').write_bytes(PNG)
        (self.root/'private.txt').write_text('not image data')
        for source,status in [('photo.png','available'),('gone.png','missing'),('https://example.com/tracker.png','remote'),('private.txt','unsupported'),('data:image/png;base64,'+base64.b64encode(b'<svg onload="alert(1)"/>').decode(),'unsupported')]:
            with self.subTest(source=source):
                self.assertEqual(status,self.store.render({'source':source,'name':'test'},str(self.root),[1024])['status'])
        (self.root/'alias.png').symlink_to(self.root/'photo.png')
        self.assertEqual('missing',self.store.render({'source':'alias.png','name':'alias'},str(self.root),[1024])['status'])

    def test_preview_budget_and_cache_are_bounded(self):
        self.assertEqual('too_large',self.store.render({'source':URI,'name':'x'},str(self.root),[1])['status'])
        self.store.max_cache_bytes = len(PNG) + 2
        first=self.store.render({'source':URI,'name':'x'},str(self.root),[1024])
        second=self.store.render({'source':'data:image/png;base64,'+base64.b64encode(PNG+b'1').decode(),'name':'y'},str(self.root),[1024])
        self.assertIsNone(self.store.get(first['url'].split('=')[-1]))
        self.assertIsNotNone(self.store.get(second['url'].split('=')[-1]))
        self.assertLessEqual(self.store.size,self.store.max_cache_bytes)

    def test_context_images_and_quoted_examples_do_not_become_attachments(self):
        text='<skills_instructions>![Context](https://example.com/context.png)</skills_instructions>'
        log=self.root/'context.jsonl';log.write_text(json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':text}]}}))
        self.assertEqual(0,conversation_preview(log,offset=0)['total_messages'])
        self.assertEqual([],extract_images('```md\n![Example](/example.png)\n```',{}))

    def test_authenticated_image_route_and_evicted_detail_cache_rebuild(self):
        fixture=create_demo_fixture(self.root)
        state=DashboardState(fixture['codex_home'],fixture['app_dir'],ROOT/'assets/dashboard',fixture['pinned_file'],False)
        log=state.tools.log_path(state.tools.record(ACTIVE_ID))
        with log.open('a') as output:
            output.write(json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_image','image_url':URI}]}})+'\n')
        detail=state.session_detail(ACTIVE_ID,20,0)
        url=next(message['images'][0]['url'] for message in detail['messages'] if message.get('images'))
        state.images.entries.clear();state.images.size=0
        state.session_detail(ACTIVE_ID,20,0)
        self.assertIsNotNone(state.images.get(url.split('=')[-1]))
        server=DashboardServer(('127.0.0.1',0),state)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+url)
            self.assertEqual(401,error.exception.code)
            error.exception.close()
            opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            opener.open(base+'/?launch='+state.launch_token).close()
            with opener.open(base+url) as response:
                self.assertEqual('image/png',response.headers['Content-Type'])
                self.assertEqual('nosniff',response.headers['X-Content-Type-Options'])
                self.assertEqual(PNG,response.read())
            with self.assertRaises(urllib.error.HTTPError) as missing:opener.open(base+'/api/session-image?path=/etc/passwd')
            self.assertEqual(404,missing.exception.code)
            missing.exception.close()
        finally:
            server.shutdown();server.server_close();thread.join(1)
