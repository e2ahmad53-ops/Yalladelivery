# API 0.1.0

كل الردود JSON. الأخطاء بالشكل `{"error":"..."}` مع 400/401/403/404/409/429/500. ضع `Authorization: Bearer TOKEN` لكل مسار عدا الدخول والفحص الصحي. الجلسات تنتهي بعد 24 ساعة؛ كلمات المرور لا تُرجع في API.

| الطريقة | المسار | الدور | الجسم / الملاحظة |
|---|---|---|---|
| GET | `/api/health` | عام | حالة الخادم |
| POST | `/api/login` | عام | `phone`, `password`؛ يعيد token وuser |
| POST | `/api/logout` | الكل | يلغي الجلسة الحالية |
| GET | `/api/me` | الكل | الحساب الحالي |
| GET | `/api/accounts` | admin | حسابات منطقة الأدمن |
| POST | `/api/accounts` | admin | `name`, `phone`, `role`, `region`, `password` (10 أحرف) |
| GET | `/api/orders` | الكل | حسب الحساب والمنطقة والموعد |
| POST | `/api/orders` | store | `customer_name`, `phone`, `address`, `fee`, `route_group`, اختياري `notes`, `scheduled_at`, `lat`, `lng` |
| POST | `/api/orders/{id}/assign` | captain/admin | الكابتن يقبل بنفسه؛ الأدمن يرسل `captain_id` |
| POST | `/api/orders/{id}/status` | مرتبط | `status`: picked_up/delivered للكابتن؛ cancelled للمتجر قبل القبول وللإدارة قبل الاستلام |
| GET | `/api/orders/{id}/tracking` | مرتبط | موقع كابتن الطلب النشط فقط |
| GET | `/api/captains` | admin | مواقع وأرصدة كباتن المنطقة |
| POST | `/api/availability` | captain | `online`: true/false |
| POST | `/api/location` | captain | `lat`, `lng` |
| GET | `/api/wallet` | captain | balance/reserved/available وآخر 100 حركة |
| POST | `/api/wallet/transfer` | captain | `recipient_phone`, `amount`, `idempotency_key` |
| POST | `/api/wallet/credit` | admin | `captain_id`, `amount`, `idempotency_key` |
| POST | `/api/support` | store/captain | يعيد id محادثة الدعم الخاصة بالحساب |
| GET | `/api/threads` | الكل | المحادثات المسموحة فقط |
| GET | `/api/threads/{id}/messages` | مرتبط | رسائل نصية |
| POST | `/api/threads/{id}/messages` | مرتبط | `body` حتى 2000 حرف |

المبالغ كلها بالفلس، لا بالأعداد العشرية. الأوقات Unix بالثواني. المنطقة محددة في الحساب ولا يختارها المتجر في كل طلب. الهواتف مطابقة حرفياً في هذه النسخة؛ أدخل صيغة موحدة عند إنشاء الحسابات.

مثال إنشاء طلب: `{"customer_name":"عميل","phone":"0790000000","address":"خلدا، عنوان تجريبي","fee":2000,"route_group":"خلدا"}`.

الطلبات المعروضة لكباتن لم يقبلوها لا تحتوي اسم الزبون أو هاتفه أو إحداثياته أو ملاحظاته. عنوان التوصيل ومجموعة الطريق وسعر التوصيل يظهرون لتقدير قبول الطلب.
