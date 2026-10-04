"""Build-only Firebase config. This cannot receive real FCM. Never use for a pilot."""
import json
from pathlib import Path
path=Path(__file__).resolve().parents[1]/'android/app/google-services.json'
if path.exists(): raise SystemExit('Refusing to overwrite existing Firebase config')
path.write_text(json.dumps({'project_info':{'project_number':'123456789000','project_id':'burjeel-build-fixture','storage_bucket':'burjeel-build-fixture.appspot.com'},'client':[{'client_info':{'mobilesdk_app_id':'1:123456789000:android:0123456789abcdef','android_client_info':{'package_name':'com.burjeel.edcall'}},'api_key':[{'current_key':'AIzaSyBUILD_ONLY_NO_LIVE_FCM_00000000000'}]}],'configuration_version':'1'}))
print('Created BUILD-ONLY Firebase fixture. No live notifications.')
