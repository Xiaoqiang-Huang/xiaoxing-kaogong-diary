import io
import os
import tempfile
import unittest

os.environ['APP_ENV'] = 'testing'
os.environ['FLASK_DEBUG'] = 'false'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['ANTHROPIC_API_KEY'] = ''
os.environ['ANTHROPIC_BASE_URL'] = ''
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

import app as app_module
import ai_engine as ai_engine_module
import news_fetcher as news_fetcher_module
from app import app, db
from models import User, Diary
from ai_engine import FourSagesEngine
from news_fetcher import NewsFetcher, DailyReportGenerator


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            DATA_PATH=self.temp_dir.name,
            DIARY_MD_PATH=self.temp_dir.name,
            ANTHROPIC_API_KEY='',
            ANTHROPIC_BASE_URL='',
            ALLOW_PUBLIC_REGISTRATION=True,
            REGISTRATION_INVITE_CODE='',
            LOGIN_MAX_ATTEMPTS=8,
            LOGIN_RATE_LIMIT_SECONDS=300,
            REGISTER_MAX_ATTEMPTS=6,
            REGISTER_RATE_LIMIT_SECONDS=600
        )
        app.tables_created = True
        app_module.login_attempts.clear()
        app_module.register_attempts.clear()
        with app.app_context():
            db.drop_all()
            db.create_all()
            ai_engine_module.init_ai_engine(db, User)
            app_module.init_ai_engine()

        self.client = app.test_client()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def login(self):
        with app.app_context():
            user = User(username='tester')
            user.set_password('123456')
            db.session.add(user)
            db.session.commit()

        response = self.client.post('/api/login', json={
            'username': 'tester',
            'password': '123456'
        })
        self.assertEqual(response.status_code, 200)

    def test_health_check_has_security_headers(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('X-Content-Type-Options', response.headers)
        self.assertEqual(response.headers['X-Frame-Options'], 'SAMEORIGIN')

    def test_kaogong_requires_login(self):
        response = self.client.get('/api/kaogong/dashboard')
        self.assertEqual(response.status_code, 401)

    def test_xingce_statistics_are_recalculated_on_update_and_delete(self):
        self.login()

        add_response = self.client.post('/api/kaogong/xingce/question', json={
            'question_type': 'verbal',
            'content': '测试题',
            'correct_answer': 'A',
            'user_answer': 'B',
            'is_correct': False
        })
        self.assertEqual(add_response.status_code, 200)
        question_id = add_response.get_json()['question']['id']

        stats_response = self.client.get('/api/kaogong/xingce/statistics')
        stats = stats_response.get_json()['statistics']['overall']
        self.assertEqual(stats['total'], 1)
        self.assertEqual(stats['correct'], 0)

        update_response = self.client.put(
            f'/api/kaogong/xingce/question/{question_id}',
            json={'user_answer': 'A', 'is_correct': True}
        )
        self.assertEqual(update_response.status_code, 200)

        stats_response = self.client.get('/api/kaogong/xingce/statistics')
        stats = stats_response.get_json()['statistics']['overall']
        self.assertEqual(stats['total'], 1)
        self.assertEqual(stats['correct'], 1)

        delete_response = self.client.delete(f'/api/kaogong/xingce/question/{question_id}')
        self.assertEqual(delete_response.status_code, 200)

        stats_response = self.client.get('/api/kaogong/xingce/statistics')
        stats = stats_response.get_json()['statistics']['overall']
        self.assertEqual(stats['total'], 0)
        self.assertEqual(stats['correct'], 0)

    def test_dashboard_returns_today_plan_for_empty_data(self):
        self.login()
        response = self.client.get('/api/kaogong/dashboard')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('today_plan', data)
        self.assertEqual(data['today_plan']['focus_type'], 'verbal')
        self.assertGreaterEqual(len(data['today_plan']['actions']), 3)

    def test_home_greeting_uses_current_username(self):
        self.login()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('const username = "tester";', html)
        self.assertIn('safeUserDisplayName', html)

    def test_home_uses_blocking_css_to_prevent_fouc(self):
        self.login()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/static/css/style.css?v=20260508-collapse-visible"', html)
        self.assertNotIn('media="print" onload', html)
        self.assertIn('app-booting', html)
        self.assertIn('/static/js/voice-utils.js?v=20260508-collapse-visible', html)

    def test_user_facing_templates_do_not_async_load_primary_css(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        for name in ['index.html', 'login.html', 'history.html', 'kaogong.html', 'settings.html']:
            with self.subTest(template=name):
                path = os.path.join(template_dir, name)
                with open(path, encoding='utf-8') as f:
                    html = f.read()
                self.assertNotIn('media="print" onload', html)
                self.assertNotIn("this.media='all'", html)

    def test_conversation_load_scrolls_to_latest_message(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        app_js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'app.js')
        with open(os.path.join(template_dir, 'index.html'), encoding='utf-8') as f:
            html = f.read()
        with open(app_js_path, encoding='utf-8') as f:
            js = f.read()

        self.assertIn('scrollToLatest(messagesDiv, messagesDiv.lastElementChild, { smooth: false })', html)
        self.assertIn('scrollMessagesToBottom', js)
        self.assertIn('setTimeout(scroll, 320)', js)

    def test_mobile_input_can_collapse_to_expand_ball(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        app_js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'app.js')
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'style.css')
        with open(os.path.join(template_dir, 'index.html'), encoding='utf-8') as f:
            html = f.read()
        with open(app_js_path, encoding='utf-8') as f:
            js = f.read()
        with open(css_path, encoding='utf-8') as f:
            css = f.read()

        self.assertIn('id="inputExpandBall"', html)
        self.assertIn('id="collapseInputBtn"', html)
        self.assertIn('aria-label="收起输入区为右下角悬浮按钮"', html)
        self.assertIn('收起输入', html)
        self.assertIn('写', html)
        self.assertIn('collapsed-to-ball', js)
        self.assertIn('.input-container.collapsed-to-ball', css)
        self.assertIn('.chat-container.has-background .input-container.collapsed-to-ball', css)
        self.assertIn('.input-toolbar .input-collapse-btn', css)
        self.assertIn('position: absolute', css)
        self.assertIn('box-shadow: 0 8px 22px rgba(37, 99, 235, 0.34)', css)

    def test_home_uses_server_voice_button_not_old_web_speech_controls(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        app_js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'app.js')
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'style.css')
        with open(os.path.join(template_dir, 'index.html'), encoding='utf-8') as f:
            html = f.read()
        with open(app_js_path, encoding='utf-8') as f:
            js = f.read()
        with open(css_path, encoding='utf-8') as f:
            css = f.read()

        self.assertNotIn('id="voiceBtn"', html)
        self.assertNotIn('id="voiceSettingsBtn"', html)
        self.assertNotIn('id="voiceSettingsModal"', html)
        self.assertIn('id="serverVoiceBtn"', html)
        self.assertIn('/api/voice/transcribe', html)
        self.assertIn('new MediaRecorder', html)
        self.assertIn('.voice-input-btn.recording', css)
        self.assertIn('voiceSettings.enabledInput = false', html)
        self.assertIn('voiceSettings.enabledOutput = false', html)

    def test_mobile_main_nav_stays_visible(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'style.css')
        with open(os.path.join(template_dir, 'index.html'), encoding='utf-8') as f:
            html = f.read()
        with open(css_path, encoding='utf-8') as f:
            css = f.read()

        self.assertIn('class="mobile-main-nav"', html)
        self.assertIn('<a href="/history">历史日记</a>', html)
        self.assertIn('<a href="/kaogong">考公复盘</a>', html)
        self.assertIn('top: var(--titlebar-h)', css)
        self.assertIn('overflow-x: auto', css)

    def test_report_config_save_and_startup_prepare_today_report(self):
        app_js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'app.js')
        with open(app_js_path, encoding='utf-8') as f:
            js = f.read()

        self.assertIn('/api/report/today?ensure=true', js)
        self.assertIn('setTimeout(ensureTodayReportPrepared, 800)', js)
        self.assertIn('today_report_generated', js)

    def test_mobile_emotion_chart_has_visible_bars(self):
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'style.css')
        with open(css_path, encoding='utf-8') as f:
            css = f.read()

        self.assertIn('#emotionChart', css)
        self.assertIn('overflow-x: auto', css)
        self.assertIn('min-width: 6px', css)
        self.assertIn('min-height: 52px', css)
        self.assertIn('height: 190px', css)

    def test_chat_background_is_wallpaper_like_and_assistant_bubble_wider(self):
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'style.css')
        with open(css_path, encoding='utf-8') as f:
            css = f.read()

        self.assertIn('max-width: min(1440px, 100vw)', css)
        self.assertIn('.chat-container.has-background .messages', css)
        self.assertIn('background: transparent', css)
        self.assertIn('max-width: min(98%, 1280px)', css)
        self.assertIn('rgba(255, 255, 255, 0.78)', css)

    def test_mobile_chat_bubbles_use_nearly_full_width(self):
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'style.css')
        with open(css_path, encoding='utf-8') as f:
            css = f.read()

        self.assertIn('width: min(98%, 1280px)', css)
        self.assertIn('width: calc(100vw - 20px)', css)
        self.assertIn('width: calc(100vw - 16px)', css)
        self.assertIn('padding: 8px 4px 180px', css)

    def test_history_page_has_mobile_layout_overrides(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        with open(os.path.join(template_dir, 'history.html'), encoding='utf-8') as f:
            html = f.read()

        self.assertIn('@media (max-width: 768px)', html)
        self.assertIn('grid-template-columns: 1fr 1fr', html)
        self.assertIn('overflow-wrap: anywhere', html)
        self.assertIn('width: 100% !important', html)

    def test_voice_transcribe_endpoint_reports_missing_provider(self):
        self.login()
        response = self.client.post('/api/voice/transcribe')
        self.assertEqual(response.status_code, 400)

        app.config['SPEECH_TO_TEXT_PROVIDER'] = ''
        data = {
            'audio': (tempfile.SpooledTemporaryFile(), 'voice.webm')
        }
        data['audio'][0].write(b'test')
        data['audio'][0].seek(0)
        response = self.client.post('/api/voice/transcribe', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 501)
        self.assertIn('服务器端语音转文字未配置', response.get_json()['error'])

    def test_input_ball_expands_from_container_click_and_cache_busts_assets(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        app_js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'app.js')
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'style.css')
        with open(os.path.join(template_dir, 'index.html'), encoding='utf-8') as f:
            html = f.read()
        with open(app_js_path, encoding='utf-8') as f:
            js = f.read()
        with open(css_path, encoding='utf-8') as f:
            css = f.read()

        self.assertIn('20260508-collapse-visible', html)
        self.assertIn("inputContainer.classList.contains('collapsed-to-ball')", js)
        self.assertIn('touchend', js)
        self.assertIn('position: fixed', css)
        self.assertIn('pointer-events: auto', css)

    def test_interview_practice_uses_server_voice_transcription(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'kaogong.js')
        with open(os.path.join(template_dir, 'kaogong.html'), encoding='utf-8') as f:
            html = f.read()
        with open(js_path, encoding='utf-8') as f:
            js = f.read()

        self.assertIn('请直接输入你的回答', html)
        self.assertIn('文字答题模式', html)
        self.assertIn('id="interviewVoiceBtn"', html)
        self.assertIn('服务器端 faster-whisper 转写', html)
        self.assertIn('20260509-voice-records-register', html)
        self.assertNotIn('id="startRecordBtn"', html)
        self.assertNotIn('id="voiceWaveform"', html)
        self.assertNotIn('SpeechRecognition', js)
        self.assertIn('startTextAnswerTimer()', js)
        self.assertIn('/api/voice/transcribe', js)
        self.assertIn('new MediaRecorder', js)
        self.assertIn('toggleInterviewVoiceRecording', js)

    def test_interview_records_can_open_detail_modal(self):
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'kaogong.js')
        with open(os.path.join(template_dir, 'kaogong.html'), encoding='utf-8') as f:
            html = f.read()
        with open(js_path, encoding='utf-8') as f:
            js = f.read()

        self.assertIn('id="interviewRecordModal"', html)
        self.assertIn('id="interviewRecordDetail"', html)
        self.assertIn('openInterviewRecord(${r.id})', js)
        self.assertIn('查看详情', js)
        self.assertIn('closeInterviewRecordModal', js)

    def test_ai_prompt_uses_current_user_name(self):
        with app.app_context():
            user = User(username='alice')
            user.set_password('123456')
            db.session.add(user)
            db.session.commit()

            engine = FourSagesEngine(api_key='')
            prompt = engine.get_system_prompt(user.id)

        self.assertIn('你是alice的日记助手', prompt)
        self.assertIn('当前用户称呼：alice', prompt)
        self.assertNotIn('你是某个固定用户的日记助手', prompt)

    def test_kaogong_upload_rejects_invalid_extension(self):
        self.login()
        response = self.client.post(
            '/api/kaogong/upload',
            data={
                'type': 'document',
                'file': (io.BytesIO(b'not allowed'), 'payload.exe')
            },
            content_type='multipart/form-data'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.get_json())

    def test_kaogong_upload_uses_document_directory(self):
        self.login()
        response = self.client.post(
            '/api/kaogong/upload',
            data={
                'type': 'document',
                'file': (io.BytesIO(b'notes'), 'notes.txt')
            },
            content_type='multipart/form-data'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('/static/uploads/docs/', response.get_json()['url'])

    def test_interview_standards_and_questions_include_guidance(self):
        self.login()

        standards_response = self.client.get('/api/kaogong/interview/standards')
        self.assertEqual(standards_response.status_code, 200)
        standards = standards_response.get_json()
        self.assertIn('综合分析能力', standards['dimensions'])
        self.assertIn('leaderless_group', standards['categories'])

        questions_response = self.client.get('/api/kaogong/interview/questions?category=professional')
        self.assertEqual(questions_response.status_code, 200)
        questions = questions_response.get_json()['questions']
        self.assertGreaterEqual(len(questions), 1)
        self.assertIn('guidance', questions[0])
        self.assertIn('专业能力', questions[0]['measured_elements'])

    def test_rule_based_interview_evaluation_uses_official_dimensions(self):
        self.login()

        response = self.client.post('/api/kaogong/interview/evaluate', json={
            'category': 'emergency',
            'question': '窗口系统故障，群众排队较多，你怎么处理？',
            'answer': '首先我会稳住现场，安抚群众情绪；其次核实系统故障情况并及时报告；然后启动备用流程，分流急件；最后复盘问题，完善预案。'
        })
        self.assertEqual(response.status_code, 200)
        evaluation = response.get_json()['evaluation']
        self.assertIn('应变能力', evaluation['scores'])
        self.assertIn('言语表达能力', evaluation['scores'])
        self.assertIn('next_drill', evaluation)
        self.assertIn('objective_assessment', evaluation)
        self.assertIn('encouragement', evaluation)
        self.assertGreater(len(evaluation['encouragement']), 20)

    def test_interview_record_saves_ai_evaluation(self):
        self.login()

        response = self.client.post('/api/kaogong/interview/record', json={
            'category': 'emergency',
            'question': '窗口系统故障，群众排队较多，你怎么处理？',
            'answer_text': '先安抚群众，再核实故障并报告，最后复盘完善预案。',
            'ai_evaluation': {
                'summary': '评价已生成',
                'encouragement': '已经完成一次有效练习。'
            }
        })
        self.assertEqual(response.status_code, 200)
        record = response.get_json()['record']
        self.assertEqual(record['ai_evaluation']['summary'], '评价已生成')
        self.assertIn('encouragement', record['ai_evaluation'])
        with app.app_context():
            diary = Diary.query.filter_by(user_id=1).first()
            self.assertIsNotNone(diary)
            self.assertIn('面试复盘评价', diary.content)
            self.assertIn('窗口系统故障', diary.content)

    def test_diary_mode_chat_appends_user_and_ai_to_today_diary(self):
        self.login()

        response = self.client.post('/api/chat', json={
            'message': '今天完成了一次行测复盘。',
            'style': 'mengmei'
        })
        self.assertEqual(response.status_code, 200)

        with app.app_context():
            diary = Diary.query.filter_by(user_id=1).first()
            self.assertIsNotNone(diary)
            self.assertIn('用户记录', diary.content)
            self.assertIn('今天完成了一次行测复盘', diary.content)
            self.assertIn('AI回应', diary.content)

    def test_public_registration_can_be_disabled(self):
        app.config['ALLOW_PUBLIC_REGISTRATION'] = False
        app.config['REGISTRATION_INVITE_CODE'] = ''

        response = self.client.post('/api/register', json={
            'username': 'new_user',
            'password': '123456'
        })
        self.assertEqual(response.status_code, 403)

    def test_public_registration_invite_code_allows_signup(self):
        app.config['ALLOW_PUBLIC_REGISTRATION'] = False
        app.config['REGISTRATION_INVITE_CODE'] = 'invite-123'

        response = self.client.post('/api/register', json={
            'username': 'invited_user',
            'password': '123456',
            'invite_code': 'invite-123'
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['user']['username'], 'invited_user')

    def test_public_registration_is_rate_limited(self):
        app.config['REGISTER_MAX_ATTEMPTS'] = 2
        app.config['REGISTER_RATE_LIMIT_SECONDS'] = 300

        for _ in range(2):
            response = self.client.post('/api/register', json={})
            self.assertEqual(response.status_code, 400)

        response = self.client.post('/api/register', json={})
        self.assertEqual(response.status_code, 429)
        self.assertIn('注册尝试过多', response.get_json()['error'])

    def test_public_launcher_respects_env_registration_switch(self):
        script_path = os.path.join(os.path.dirname(__file__), '..', 'start_public_fast.py')
        with open(script_path, encoding='utf-8') as f:
            script = f.read()

        load_index = script.index('load_dotenv(ROOT / ".env")')
        default_index = script.index('os.environ.setdefault("ALLOW_PUBLIC_REGISTRATION", "false")')
        self.assertLess(load_index, default_index)

    def test_auth_endpoints_reject_empty_or_non_json_bodies(self):
        response = self.client.post('/api/login', data='not-json', content_type='text/plain')
        self.assertEqual(response.status_code, 400)
        self.assertIn('用户名和密码不能为空', response.get_json()['error'])

        response = self.client.post('/api/register', data='not-json', content_type='text/plain')
        self.assertEqual(response.status_code, 400)
        self.assertIn('用户名和密码不能为空', response.get_json()['error'])

    def test_settings_are_created_with_default_features(self):
        self.login()

        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        settings = response.get_json()['settings']
        self.assertTrue(settings['enabled_features']['diary']['enabled'])
        self.assertTrue(settings['enabled_features']['kaogong']['modules']['interview'])

        with app.app_context():
            user = User.query.filter_by(username='tester').first()
            prefs = user.preferences
            self.assertIsNotNone(prefs)
            self.assertTrue(prefs.enabled_features)

    def test_settings_update_can_create_defaults_before_theme_change(self):
        self.login()

        response = self.client.put('/api/settings', json={'theme': 'dark'})
        self.assertEqual(response.status_code, 200)
        settings = response.get_json()['settings']
        self.assertEqual(settings['theme'], 'dark')
        self.assertTrue(settings['enabled_features']['notifications']['daily_reminder'])

    def test_official_report_source_outputs_real_links(self):
        fetcher = NewsFetcher()

        def fake_read_url(url, timeout=8):
            if 'people.com.cn' in url:
                return '''<?xml version="1.0" encoding="UTF-8"?>
                <rss><channel><item>
                <title>基层治理服务群众新举措</title>
                <link>https://politics.people.com.cn/n1/test.html</link>
                <pubDate>Fri, 08 May 2026 08:00:00 GMT</pubDate>
                <description>围绕公共服务提质增效。</description>
                </item></channel></rss>''', url
            if 'gov.cn' in url:
                return '''pushInfoJsonpCallBack([
                    {"title":"国务院部署稳就业政策措施","link":"https://www.gov.cn/test.htm","pubDate":"2026-05-08","description":"稳就业与公共服务"}
                ])''', url
            return '''<html><body>
                <a href="https://www.xinhuanet.com/politics/test.htm">科技创新赋能社会治理</a>
            </body></html>''', url

        fetcher._read_url = fake_read_url
        section = fetcher.fetch_official_items('custom:考公', per_source=2, max_items=5)

        self.assertEqual(section['type'], 'official_news')
        self.assertIn('[基层治理服务群众新举措](https://politics.people.com.cn/n1/test.html)', section['content'])
        self.assertIn('[国务院部署稳就业政策措施](https://www.gov.cn/test.htm)', section['content'])
        self.assertIn('申论/面试角度', section['content'])
        self.assertNotIn('正在整理中', section['content'])

    def test_custom_report_topic_generates_official_section(self):
        class FakeFetcher:
            def __init__(self):
                self.queries = []

            def fetch_ai_guided_topic_news(self, topic, ai_engine=None, max_items=5):
                self.queries.append((topic, max_items))
                return {
                    'type': 'topic_news',
                    'title': f'{topic}｜相关资讯',
                    'content': '[基层治理测试](https://www.gov.cn/test.htm)',
                    'source': '测试官方源',
                    'timestamp': '2026-05-08T08:00:00',
                    'items': []
                }

        fetcher = FakeFetcher()
        generator = DailyReportGenerator(db=None, ai_engine=None, news_fetcher=fetcher)
        section = generator._generate_section('custom:基层治理', user_id=1)

        self.assertEqual(section['title'], '基层治理')
        self.assertIn('基层治理测试', section['content'])
        self.assertEqual(fetcher.queries[0], ('基层治理', 5))

    def test_report_topics_are_deduplicated(self):
        class FakeFetcher:
            def fetch_ai_guided_topic_news(self, topic, ai_engine=None, max_items=5):
                return {
                    'type': 'topic_news',
                    'title': f'{topic}｜相关资讯',
                    'content': f'话题内容：{topic}',
                    'source': '测试搜索源',
                    'timestamp': '2026-05-08T08:00:00',
                    'items': []
                }

            def fetch_weather(self):
                return {'type': 'weather', 'title': '今日天气', 'content': '天气', 'source': '天气'}

        generator = DailyReportGenerator(db=None, ai_engine=None, news_fetcher=FakeFetcher())
        topics = [
            '行业动态与新闻',
            '行业动态与新闻',
            '考公申论素材与面试表达',
            '今日天气与提醒'
        ]

        normalized = generator._normalize_topics(topics)
        sections = []
        seen = set()
        for topic in normalized:
            section = generator._generate_section(topic, user_id=1)
            key = generator._section_key(section)
            if key not in seen:
                seen.add(key)
                sections.append(section)

        self.assertEqual(normalized, ['行业动态与新闻', '考公申论素材与面试表达', '今日天气与提醒'])
        self.assertEqual([section['type'] for section in sections], ['topic_news', 'topic_news', 'weather'])
        self.assertIn('行业动态与新闻', sections[0]['title'])
        self.assertIn('考公申论素材与面试表达', sections[1]['title'])

    def test_time_description_respects_rss_timezone(self):
        fetcher = NewsFetcher()
        original_datetime = news_fetcher_module.datetime

        class FixedDatetime(original_datetime):
            @classmethod
            def now(cls, tz=None):
                fixed = original_datetime(2026, 5, 8, 10, 0, 0)
                if tz:
                    return fixed.replace(tzinfo=tz)
                return fixed

        try:
            news_fetcher_module.datetime = FixedDatetime
            self.assertEqual(
                fetcher._get_time_description('Fri, 08 May 2026 08:00:00 GMT'),
                '2小时前'
            )
        finally:
            news_fetcher_module.datetime = original_datetime

    def test_ai_guided_topic_news_uses_ai_queries_and_real_search_results(self):
        class FakeAIClient:
            class Messages:
                def create(self, **kwargs):
                    class Response:
                        class Content:
                            text = "嵌入式开发 最新新闻\n嵌入式 Linux 政策 动态"
                        content = [Content()]
                    return Response()
            messages = Messages()

        class FakeAIEngine:
            client = FakeAIClient()

            def is_available(self):
                return True

        fetcher = NewsFetcher()

        def fake_fetch_web_news_items(query, max_items=5):
            return {
                'type': 'topic_news',
                'title': f'{query}｜相关资讯',
                'content': 'content',
                'source': '测试搜索',
                'timestamp': '2026-05-08T08:00:00',
                'items': [{
                    'title': f'{query} 结果',
                    'url': f'https://example.com/{len(query)}',
                    'source': '测试搜索',
                    'published': 'Fri, 08 May 2026 08:00:00 GMT',
                    'time_desc': '2小时前',
                    'summary': '摘要'
                }]
            }

        fetcher.fetch_web_news_items = fake_fetch_web_news_items
        section = fetcher.fetch_ai_guided_topic_news('嵌入式开发', ai_engine=FakeAIEngine(), max_items=2)

        self.assertEqual(section['type'], 'topic_news')
        self.assertIn('嵌入式开发｜相关资讯', section['title'])
        self.assertIn('AI搜索词', section['content'])
        self.assertIn('嵌入式开发 最新新闻', section['content'])
        self.assertEqual(len(section['items']), 2)

    def test_ai_web_search_tool_results_are_used_first(self):
        class ToolResultBlock:
            type = 'tool_result'
            content = str([{
                'text': [{
                    'title': '新华社报道社会热点治理新进展',
                    'link': 'https://www.news.cn/test.htm',
                    'content': '围绕社会治理和民生服务的权威报道。',
                    'source': '新华网'
                }]
            }])

        class FakeAIClient:
            class Messages:
                def __init__(self):
                    self.kwargs = None
                    self.calls = []

                def create(self, **kwargs):
                    self.kwargs = kwargs
                    self.calls.append(kwargs)
                    class Response:
                        content = [ToolResultBlock()]
                    return Response()

            def __init__(self):
                self.messages = self.Messages()

        class FakeAIEngine:
            def __init__(self):
                self.client = FakeAIClient()

            def is_available(self):
                return True

        engine = FakeAIEngine()
        fetcher = NewsFetcher()
        fetcher.fetch_web_news_items = lambda query, max_items=5: {"items": [], "source": "测试"}
        section = fetcher.fetch_ai_guided_topic_news('社会热点', ai_engine=engine, max_items=3)

        self.assertEqual(section['type'], 'topic_news')
        self.assertEqual(section['source'], 'AI API 网页搜索')
        self.assertIn('新华社报道社会热点治理新进展', section['content'])
        self.assertIn('中国媒体优先', section['content'])
        self.assertEqual(engine.client.messages.calls[0]['tools'][0]['type'], 'web_search_20250305')
        self.assertIn('人民网、新华网、央视新闻', engine.client.messages.calls[0]['messages'][0]['content'])
        self.assertIn('搜索词必须包含原始话题「社会热点」', engine.client.messages.calls[0]['messages'][0]['content'])

    def test_ai_web_search_extracts_concatenated_tool_result_payload(self):
        class ToolResultBlock:
            type = 'tool_result'
            content = (
                "[{'text': [{'title': '人民网关注社会热点民生议题', "
                "'link': 'https://people.com.cn/test.htm', "
                "'content': '围绕民生服务和社会治理展开报道。', "
                "'source': '人民网'}], 'type': 'text'}]"
                "[[{\"title\":\"央视新闻跟进基层治理新实践\","
                "\"link\":\"https://news.cctv.com/test.shtml\","
                "\"content\":\"基层治理相关权威报道。\","
                "\"source\":\"央视新闻\"}]]"
            )

        class Response:
            content = [ToolResultBlock()]

        fetcher = NewsFetcher()
        items = fetcher._extract_web_search_items(Response(), max_items=3)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['title'], '人民网关注社会热点民生议题')
        self.assertEqual(items[1]['source'], '央视新闻')

    def test_ai_web_search_prefers_ai_formatted_summary(self):
        class RawToolResultBlock:
            type = 'tool_result'
            content = str([{
                'text': [{
                    'title': '人民网_网上的人民日报',
                    'link': 'https://www.people.com.cn/',
                    'content': '门户首页内容。',
                    'source': '人民网'
                }]
            }])

        class FormattedTextBlock:
            type = 'text'
            text = """根据搜索结果，为您整理以下适合日报展示的社会热点相关资讯：

## 第1条
**标题**：最高检发布社会治理相关最新情况
**URL**：http://society.people.com.cn/test.htm
**来源**：人民网
**摘要**：来自权威中文媒体的社会热点报道摘要。
"""

        class FakeAIClient:
            class Messages:
                def create(self, **kwargs):
                    class Response:
                        content = [RawToolResultBlock(), FormattedTextBlock()]
                    return Response()

            def __init__(self):
                self.messages = self.Messages()

        class FakeAIEngine:
            client = FakeAIClient()

            def is_available(self):
                return True

        fetcher = NewsFetcher()
        section = fetcher.fetch_ai_web_search_topic_news('社会热点', ai_engine=FakeAIEngine(), max_items=2)

        self.assertIn('最高检发布社会治理相关最新情况', section['content'])
        self.assertNotIn('人民网_网上的人民日报', section['content'])
        self.assertEqual(section['items'][0]['source'], '人民网')

    def test_ai_web_search_uses_ai_to_format_raw_candidates(self):
        class RawToolResultBlock:
            type = 'tool_result'
            content = str([{
                'text': [
                    {
                        'title': '人民网_网上的人民日报',
                        'link': 'https://www.people.com.cn/',
                        'content': '门户首页内容。',
                        'source': '人民网'
                    },
                    {
                        'title': '社会·法治--人民网',
                        'link': 'http://society.people.com.cn/test.htm',
                        'content': '最高检发布社会治理相关最新情况。',
                        'source': '人民网'
                    }
                ]
            }])

        class FormatterTextBlock:
            type = 'text'
            text = '[{"title":"最高检发布社会治理相关最新情况","url":"http://society.people.com.cn/test.htm","source":"人民网","summary":"来自中国媒体的社会热点报道。","published":""}]'

        class FakeAIClient:
            class Messages:
                def __init__(self):
                    self.calls = []

                def create(self, **kwargs):
                    self.calls.append(kwargs)
                    if 'tools' in kwargs:
                        class SearchResponse:
                            content = [RawToolResultBlock()]
                        return SearchResponse()

                    class FormatResponse:
                        content = [FormatterTextBlock()]
                    return FormatResponse()

            def __init__(self):
                self.messages = self.Messages()

        class FakeAIEngine:
            def __init__(self):
                self.client = FakeAIClient()

            def is_available(self):
                return True

        engine = FakeAIEngine()
        fetcher = NewsFetcher()
        fetcher.fetch_web_news_items = lambda query, max_items=5: {"items": [], "source": "测试"}
        section = fetcher.fetch_ai_web_search_topic_news('社会热点', ai_engine=engine, max_items=1)

        self.assertEqual(len(engine.client.messages.calls), 2)
        self.assertIn('最高检发布社会治理相关最新情况', section['content'])
        self.assertNotIn('人民网_网上的人民日报', section['content'])
        self.assertNotIn('https://www.people.com.cn/', engine.client.messages.calls[1]['messages'][0]['content'])
        self.assertIn('http://society.people.com.cn/test.htm', engine.client.messages.calls[1]['messages'][0]['content'])

    def test_china_media_topics_are_augmented_with_targeted_news_candidates(self):
        fetcher = NewsFetcher()
        seen_queries = []

        def fake_fetch_web_news_items(query, max_items=5):
            seen_queries.append(query)
            return {
                "items": [{
                    "title": "人民网报道社会治理新进展",
                    "url": "http://society.people.com.cn/test.htm",
                    "source": "人民网",
                    "summary": "社会治理相关报道。",
                    "published": "",
                    "time_desc": ""
                }],
                "source": "测试"
            }

        fetcher.fetch_web_news_items = fake_fetch_web_news_items
        items = fetcher._augment_with_china_media_news('社会热点', [], max_candidates=3)

        self.assertTrue(any('site:people.com.cn/society' in query for query in seen_queries))
        self.assertEqual(items[0]['title'], '人民网报道社会治理新进展')

    def test_web_news_falls_back_to_bing_html_when_rss_is_html(self):
        fetcher = NewsFetcher()

        def fake_read_url(url, timeout=8):
            if 'news/search' in url:
                return '<html>not rss</html>', url
            return '''<html><body>
                <li class="b_algo">
                    <h2><a href="https://example.com/embedded">嵌入式开发最新趋势</a></h2>
                    <p>嵌入式系统与边缘计算相关资讯。</p>
                </li>
            </body></html>''', url

        fetcher._read_url = fake_read_url
        section = fetcher.fetch_web_news_items('嵌入式开发', max_items=3)

        self.assertEqual(section['type'], 'topic_news')
        self.assertIn('嵌入式开发最新趋势', section['content'])
        self.assertIn('Bing网页搜索', section['source'])
        self.assertEqual(section['items'][0]['url'], 'https://example.com/embedded')


if __name__ == '__main__':
    unittest.main()
