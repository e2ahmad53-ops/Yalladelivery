"""Bootstrap an admin or explicitly create local demo accounts; passwords are prompted."""
import argparse
import getpass
import os
from pathlib import Path
from service import Service

parser = argparse.ArgumentParser()
parser.add_argument('--demo', action='store_true', help='Create local sample store and captains too')
parser.add_argument('--name', default='المدير أبو فيصل')
parser.add_argument('--phone', required=True)
args = parser.parse_args()
path = Path(os.environ.get('YALLA_DB', str(Path(__file__).resolve().parents[1]/'data'/'yalla.sqlite3')))
path.parent.mkdir(parents=True, exist_ok=True)
service = Service(path)
password = getpass.getpass('كلمة مرور جديدة (10 أحرف على الأقل): ')
if password != getpass.getpass('تأكيد كلمة المرور: '):
    raise SystemExit('كلمتا المرور مختلفتان')
identity = service.add_user(args.name, args.phone, 'admin', '*', password)
print('تم إنشاء المدير:', identity)
if args.demo:
    for name, phone, role in [('متجر تجريبي', 'demo-store', 'store'), ('كابتن تجريبي 1', 'demo-captain-1', 'captain'), ('كابتن تجريبي 2', 'demo-captain-2', 'captain')]:
        identity = service.add_user(name, phone, role, 'السابع', password, 10_000 if role == 'captain' else 0)
        print('حساب تجريبي:', phone, identity)
print('تشغيل: python3 backend/server.py')
