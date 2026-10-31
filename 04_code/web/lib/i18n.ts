// Dictionnaire bilingue EN / AR. Conçu dès le départ pour les deux scripts (Brief §6).
// Les chiffres restent occidentaux (0-9), usuels en maths GCC.

export type Lang = "en" | "ar";

export const DICT = {
  // — Global / nav —
  "app.name": { en: "Atlas Learning", ar: "أطلس للتعلّم" },
  "app.tagline": {
    en: "Continuous, skill-by-skill mastery measurement",
    ar: "قياس مستمرّ للإتقان مهارةً مهارة",
  },
  "nav.class": { en: "My class", ar: "صفّي" },
  "nav.school": { en: "School overview", ar: "نظرة عامة على المدرسة" },
  "nav.classes": { en: "Classes & licences", ar: "الصفوف والتراخيص" },
  "nav.report": { en: "Reports", ar: "التقارير" },
  "nav.session": { en: "My session", ar: "جلستي" },
  "nav.trajectory": { en: "My child", ar: "طفلي" },
  "nav.security": { en: "Security & SSO", ar: "الأمن والدخول الموحّد" },
  "nav.linguist": { en: "Arabic review", ar: "مراجعة العربية" },
  "nav.review": { en: "Review queue", ar: "قائمة المراجعة" },
  "nav.department": { en: "Department", ar: "القسم" },
  "nav.group": { en: "Schools", ar: "المدارس" },
  "nav.signout": { en: "Sign out", ar: "تسجيل الخروج" },

  // — Coordinateur maths (C1, structure ; contenu au ticket D1) —
  "department.title": { en: "Department review", ar: "مراجعة القسم" },
  "department.subtitle": {
    en: "Your grades in this school. Open a class to see its gaps and the root causes behind them.",
    ar: "صفوفك في هذه المدرسة. افتح صفًا لترى ثغراته والأسباب الجذرية خلفها.",
  },
  "department.grade": { en: "Grade", ar: "الصف" },
  "department.classes": { en: "Classes in this grade", ar: "صفوف هذا المستوى" },
  "department.noclass": {
    en: "No class carries this grade yet. Your school admin sets a class's grade in the classes view.",
    ar: "لا يحمل أي صف هذا المستوى بعد. يحدّد مسؤول مدرستك مستوى الصف في عرض الصفوف.",
  },
  "department.open": { en: "Open class", ar: "افتح الصف" },
  "department.review.title": { en: "Common root causes across classes", ar: "الأسباب الجذرية المشتركة بين الصفوف" },
  "department.review.body": {
    en: "This view will show the root causes shared across classes of the grade, the actions taken and their measured effect, and your recorded decision. It never shows results per teacher.",
    ar: "ستعرض هذه اللوحة الأسباب الجذرية المشتركة بين صفوف المستوى، والإجراءات المتّخذة وأثرها المقيس، وقرارك المسجَّل. لا تعرض أبدًا نتائج بحسب المعلّم.",
  },
  "department.noscope": {
    en: "No grade is assigned to you in this school. Ask your IT admin to set your department scope.",
    ar: "لم يُسنَد إليك أي مستوى في هذه المدرسة. اطلب من مسؤول تقنية المعلومات تحديد نطاق قسمك.",
  },

  // — Groupe scolaire (G1, structure ; contenu au ticket D3) —
  "group.title": { en: "Schools overview", ar: "نظرة عامة على المدارس" },
  "group.subtitle": {
    en: "Every school in your group, compared on the same skill graph — never on raw curriculum scores.",
    ar: "كل مدارس مجموعتك، مقارنةً على رسم المهارات نفسه — لا على درجات المنهج الخام أبدًا.",
  },
  "group.kpi.schools": { en: "Schools", ar: "المدارس" },
  "group.kpi.students": { en: "Students", ar: "الطلاب" },
  "group.kpi.classes": { en: "Classes", ar: "الصفوف" },
  "group.school.open": { en: "Open school", ar: "افتح المدرسة" },
  "group.school.loading": { en: "Loading…", ar: "جارٍ التحميل…" },
  "group.school.unavailable": { en: "Not available", ar: "غير متاح" },
  "group.common.title": { en: "Root causes shared across schools", ar: "الأسباب الجذرية المشتركة بين المدارس" },
  "group.common.body": {
    en: "This view will show the root causes common to several schools, by grade, with the number of students each one blocks — on the neutral skill graph.",
    ar: "ستعرض هذه اللوحة الأسباب الجذرية المشتركة بين عدة مدارس، بحسب المستوى، مع عدد الطلاب الذين يعيقهم كل سبب — على رسم المهارات المحايد.",
  },
  "group.noschool": {
    en: "No school is attached to this group yet.",
    ar: "لم تُلحَق أي مدرسة بهذه المجموعة بعد.",
  },
  "group.unlocked.pending": { en: "Unlocks: measured after the first weekly loop", ar: "الفتح: يُقاس بعد أول حلقة أسبوعية" },

  // — File de revue de la banque (O2) —
  "review.title": { en: "Review queue", ar: "قائمة المراجعة" },
  "review.subtitle": {
    en: "One queue for everything the bank needs a human to look at. Fix at the template, not item by item.",
    ar: "قائمة واحدة لكل ما يحتاج إلى نظرة بشرية في بنك الأسئلة. أصلِح في القالب، لا سؤالًا سؤالًا.",
  },
  "review.src.all": { en: "All", ar: "الكل" },
  "review.src.flag": { en: "Teacher flags", ar: "تنبيهات المعلّمين" },
  "review.src.validation": { en: "Failed validation", ar: "فشل التحقّق" },
  "review.src.school": { en: "From schools", ar: "من المدارس" },
  "review.src.arabic": { en: "Arabic to validate", ar: "عربية للمصادقة" },
  "review.empty": { en: "Nothing to review in this list.", ar: "لا شيء للمراجعة في هذه القائمة." },
  "review.group.notemplate": { en: "No template (school or LLM items)", ar: "بدون قالب (أسئلة مدرسية أو مولَّدة)" },
  "review.group.items": { en: "items", ar: "أسئلة" },
  "review.group.active": { en: "active", ar: "نشطة" },
  "review.group.flags": { en: "open flags", ar: "تنبيهات مفتوحة" },
  "review.item.en": { en: "Item EN", ar: "السؤال بالإنجليزية" },
  "review.item.ar": { en: "Arabic version", ar: "النسخة العربية" },
  "review.item.noar": { en: "No Arabic yet.", ar: "لا توجد عربية بعد." },
  "review.item.key": { en: "answer key", ar: "مفتاح الإجابة" },
  "review.item.version": { en: "version", ar: "الإصدار" },
  "review.item.responses": { en: "responses", ar: "إجابات" },
  "review.item.template": { en: "template", ar: "القالب" },
  "review.item.status": { en: "Status", ar: "الحالة" },
  "review.item.errors": { en: "Automatic checks", ar: "الفحوص الآلية" },
  "review.flags.title": { en: "Flags", ar: "التنبيهات" },
  "review.flags.schools": { en: "schools", ar: "مدارس" },
  "review.flag.accept": { en: "Accept flag", ar: "قبول التنبيه" },
  "review.flag.reject": { en: "Reject flag", ar: "رفض التنبيه" },
  "review.flag.accept.hint": {
    en: "Accepting takes an active item out of the served pool. Items still in review keep their status.",
    ar: "القبول يُخرج السؤال النشط من المجموعة المقدَّمة. الأسئلة التي ما تزال قيد المراجعة تحتفظ بحالتها.",
  },
  "review.versions": { en: "Versions", ar: "الإصدارات" },
  "review.lifecycle": { en: "Status cycle", ar: "دورة الحالات" },
  "review.lifecycle.note": {
    en: "New versions restart at ai_generated. Nothing skips a step.",
    ar: "الإصدارات الجديدة تبدأ من ai_generated. لا شيء يتخطّى خطوة.",
  },
  "review.action.approve": { en: "Approve (EN reviewed)", ar: "اعتماد (تمت مراجعة الإنجليزية)" },
  "review.action.quarantine": { en: "Quarantine item", ar: "حجر السؤال" },
  "review.action.reject": { en: "Reject item", ar: "رفض السؤال" },
  "review.action.activate": { en: "Activate", ar: "تفعيل" },
  "review.action.rehabilitate": { en: "Return to pool", ar: "إعادة إلى المجموعة" },
  "review.action.quarantine_template": { en: "Quarantine template", ar: "حجر القالب" },
  "review.action.regenerate": { en: "Regenerate from template", ar: "إعادة التوليد من القالب" },
  "review.action.regenerate.dry": { en: "Preview regeneration", ar: "معاينة إعادة التوليد" },
  "review.action.reason": { en: "Reason (kept in provenance)", ar: "السبب (يُحفظ في السجل)" },
  "review.action.confirm": { en: "Confirm", ar: "تأكيد" },
  "review.regen.result": {
    en: "{a} new version(s), {b} created, {c} unchanged. New versions start at ai_generated; past responses stay on the old version.",
    ar: "{a} إصدار(ات) جديدة، {b} مُنشأ، {c} بلا تغيير. تبدأ الإصدارات الجديدة من ai_generated؛ وتبقى الإجابات السابقة على الإصدار القديم.",
  },
  "review.quarantine.result": { en: "{n} active item(s) quarantined.", ar: "تم حجر {n} سؤال(أسئلة) نشطة." },
  "review.superonly": { en: "Atlas super admin only", ar: "لمسؤول أطلس الأعلى فقط" },
  "review.select": { en: "Select an item to see it in both languages.", ar: "اختر سؤالًا لعرضه باللغتين." },

  // — Curriculum : choix réservé à Atlas (Q14) —
  "curriculum.readonly": {
    en: "The displayed framework is set by Atlas for your school. Contact your Atlas account manager to change it.",
    ar: "يحدّد أطلس الإطار المعروض لمدرستك. تواصل مع مدير حسابك في أطلس لتغييره.",
  },
  "lang.toggle": { en: "العربية", ar: "English" },

  // — Auth —
  "login.title": { en: "Sign in to Atlas", ar: "تسجيل الدخول إلى أطلس" },
  "login.email": { en: "Email", ar: "البريد الإلكتروني" },
  "login.password": { en: "Password", ar: "كلمة المرور" },
  "login.mfa": { en: "Authentication code (MFA)", ar: "رمز المصادقة (MFA)" },
  "login.mfa.hint": { en: "Required for staff accounts", ar: "مطلوب لحسابات الطاقم" },
  "login.submit": { en: "Sign in", ar: "دخول" },
  "login.error": { en: "Invalid credentials.", ar: "بيانات الدخول غير صحيحة." },
  "login.mfa.required": { en: "Enter your MFA code to continue.", ar: "أدخل رمز المصادقة للمتابعة." },
  "login.demo": { en: "Demo accounts", ar: "حسابات تجريبية" },
  "login.parent": { en: "Parent? Get a login link →", ar: "ولي أمر؟ احصل على رابط دخول ←" },
  "login.staff": { en: "Coordinator or group admin without SSO? Get a sign-in link →", ar: "منسّق أو مسؤول مجموعة بدون دخول موحّد؟ احصل على رابط دخول ←" },
  "login.link.error": {
    en: "This sign-in link is invalid, already used or expired. Request a new one.",
    ar: "رابط الدخول هذا غير صالح أو مستعمل أو منتهي الصلاحية. اطلب رابطًا جديدًا.",
  },
  "staff.login.title": { en: "Sign in with a link", ar: "الدخول عبر رابط" },
  "staff.login.intro": {
    en: "For coordinators and group administrators whose school has no single sign-on. Enter the email your administrator registered and we'll send you a single-use link.",
    ar: "للمنسّقين ومسؤولي المجموعات الذين لا تملك مدرستهم دخولًا موحّدًا. أدخل البريد الذي سجّله المسؤول وسنرسل لك رابطًا لمرة واحدة.",
  },
  "staff.login.submit": { en: "Send me a link", ar: "أرسل لي رابطًا" },
  "staff.login.sent.title": { en: "Check your inbox", ar: "تحقّق من بريدك" },
  "staff.login.sent.body": {
    en: "If this email has access, a single-use link is on its way. It expires in 30 minutes.",
    ar: "إذا كان لهذا البريد صلاحية دخول، فالرابط في طريقه إليك. تنتهي صلاحيته خلال 30 دقيقة.",
  },
  "login.noprovider": {
    en: "No sign-in method is configured yet. Contact your administrator.",
    ar: "لا توجد طريقة دخول مهيّأة بعد. تواصل مع المسؤول.",
  },

  // — Onboarding (entrée IT admin) —
  "onboarding.title": { en: "Set up your school", ar: "إعداد مدرستك" },
  "onboarding.body": {
    en: "Connect your Google Workspace to provision accounts and roster automatically.",
    ar: "اربط Google Workspace لإنشاء الحسابات والقوائم تلقائيًا.",
  },
  "onboarding.cta": { en: "Continue with Google", ar: "المتابعة عبر Google" },
  "onboarding.note": {
    en: "A Google Workspace administrator account is required.",
    ar: "يلزم حساب مسؤول Google Workspace.",
  },

  // — Accès parent (lien magique) —
  "parent.login.title": { en: "Parent access", ar: "دخول ولي الأمر" },
  "parent.login.intro": {
    en: "Enter your email and we'll send you a link to your child's space.",
    ar: "أدخل بريدك الإلكتروني وسنرسل لك رابطًا إلى مساحة طفلك.",
  },
  "parent.login.submit": { en: "Send me a link", ar: "أرسل لي رابطًا" },
  "parent.login.sent.title": { en: "Check your inbox", ar: "تحقّق من بريدك" },
  "parent.login.sent.body": {
    en: "If an account exists for this email, a sign-in link is on its way.",
    ar: "إن وُجد حساب لهذا البريد، فإن رابط الدخول في طريقه إليك.",
  },
  "parent.login.expired": {
    en: "That link is invalid or expired — request a new one.",
    ar: "هذا الرابط غير صالح أو منتهي — اطلب رابطًا جديدًا.",
  },
  // Étape de confirmation du lien magique (anti-préchargement : le clic humain consomme).
  "magic.confirm.title": { en: "Almost there", ar: "خطوة أخيرة" },
  "magic.confirm.body": {
    en: "Click Continue to sign in. This link works only once.",
    ar: "اضغط «متابعة» لتسجيل الدخول. هذا الرابط يعمل مرة واحدة فقط.",
  },
  "magic.confirm.submit": { en: "Continue", ar: "متابعة" },
  "login.sso.or": { en: "or", ar: "أو" },
  "login.sso.with": { en: "Continue with", ar: "المتابعة عبر" },
  "login.sso.error": { en: "Single sign-on failed. Try again or use your password.", ar: "فشل الدخول الموحّد. حاول مجددًا أو استخدم كلمة المرور." },

  // — Enrôlement MFA (1er login staff) —
  "mfa.setup.title": { en: "Set up two-factor authentication", ar: "إعداد المصادقة الثنائية" },
  "mfa.setup.intro": {
    en: "Scan this code with Google Authenticator or Authy, then enter the 6-digit code.",
    ar: "امسح هذا الرمز عبر Google Authenticator أو Authy، ثم أدخل الرمز المكوّن من 6 أرقام.",
  },
  "mfa.setup.manual": { en: "Or enter this key manually:", ar: "أو أدخل هذا المفتاح يدويًا:" },
  "mfa.setup.code": { en: "6-digit code", ar: "الرمز المكوّن من 6 أرقام" },
  "mfa.setup.confirm": { en: "Activate", ar: "تفعيل" },
  "mfa.setup.error": { en: "Invalid code, try again.", ar: "رمز غير صحيح، حاول مجددًا." },

  // — Common —
  "common.loading": { en: "Loading…", ar: "جارٍ التحميل…" },
  "common.measured": { en: "Measured", ar: "مَقيس" },
  "common.estimated": { en: "Estimated", ar: "مُقدَّر" },
  "common.estimate.note": {
    en: "Estimated — inferred from related skills, few direct answers yet.",
    ar: "تقدير — مُستنتَج من مهارات مرتبطة، إجابات مباشرة قليلة حتى الآن.",
  },
  "common.mastered": { en: "Mastered", ar: "مُتقَن" },
  "common.inprogress": { en: "In progress", ar: "قيد التقدّم" },
  "common.notmeasured": { en: "Not yet measured", ar: "لم يُقَس بعد" },
  "common.students": { en: "students", ar: "طلاب" },
  "common.student": { en: "Student", ar: "طالب" },
  "common.close": { en: "Close", ar: "إغلاق" },
  "common.back": { en: "Back", ar: "رجوع" },
  "common.percentile": { en: "percentile", ar: "المئين" },
  "common.level": { en: "Level", ar: "المستوى" },
  "common.skills": { en: "skills", ar: "مهارات" },
  "common.gaps": { en: "gaps", ar: "ثغرات" },
  "common.next.step": { en: "next step", ar: "الخطوة التالية" },

  // — Empty / errors —
  "empty.class.title": { en: "No data for this class yet", ar: "لا توجد بيانات لهذا الصف بعد" },
  "empty.class.body": {
    en: "Once students complete their first adaptive session, gaps and priorities appear here.",
    ar: "بمجرد أن يُكمل الطلاب أول جلسة تكيّفية، تظهر الثغرات والأولويات هنا.",
  },
  "empty.student.title": { en: "Not enough data yet", ar: "البيانات غير كافية بعد" },
  "empty.student.body": {
    en: "This student needs a few more answers before we can measure with confidence.",
    ar: "يحتاج هذا الطالب إلى مزيد من الإجابات قبل أن نقيس بثقة.",
  },
  "error.generic": { en: "Something went wrong.", ar: "حدث خطأ ما." },

  // — Teacher: class view —
  "class.title": { en: "Where to focus your next lesson", ar: "أين تُركّز درسك القادم" },
  "class.subtitle": {
    en: "Priority gaps across your class, grouped by root cause.",
    ar: "الثغرات ذات الأولوية في صفّك، مجمّعة حسب السبب الجذري.",
  },
  "class.gaps.title": { en: "Class priorities", ar: "أولويات الصف" },
  "class.gaps.affected": { en: "affected", ar: "متأثّرون" },
  "class.students.title": { en: "Students", ar: "الطلاب" },
  "class.col.student": { en: "Student", ar: "الطالب" },
  "class.col.level": { en: "Level", ar: "المستوى" },
  "class.col.gaps": { en: "Gaps", ar: "الثغرات" },
  "class.col.measured": { en: "Skills measured", ar: "مهارات مقيسة" },
  "class.open": { en: "Open profile", ar: "فتح الملف" },
  "class.remediate.group": { en: "Group remediation", ar: "معالجة جماعية" },

  // — Teacher: student profile (hero) —
  "profile.title": { en: "Student profile", ar: "ملفّ الطالب" },
  "profile.diagnosis.title": { en: "Causal diagnosis", ar: "التشخيص السببي" },
  "profile.diagnosis.subtitle": {
    en: "Why this student is blocked — the root cause upstream.",
    ar: "لماذا يتعثّر هذا الطالب — السبب الجذري الأعلى في السلسلة.",
  },
  "profile.rootcause": { en: "Root cause", ar: "السبب الجذري" },
  "profile.blockedon": { en: "Blocked on", ar: "متعثّر في" },
  "profile.because": { en: "because", ar: "لأنّ" },
  "profile.mastery.title": { en: "Mastery profile", ar: "ملف الإتقان" },
  "profile.mastery.subtitle": {
    en: "Skill by skill, along the fractions pathway.",
    ar: "مهارةً مهارة، على طول مسار الكسور.",
  },
  "profile.nogaps.title": { en: "No gaps right now 🎯", ar: "لا ثغرات حاليًا 🎯" },
  "profile.nogaps.body": {
    en: "Every measured skill is on track. Keep the momentum.",
    ar: "كلّ مهارة مقيسة على المسار الصحيح. حافظ على الزخم.",
  },
  "profile.remediate": { en: "Start targeted remediation", ar: "ابدأ معالجة موجّهة" },
  "profile.othergaps": { en: "Other skills to work on", ar: "مهارات أخرى للعمل عليها" },

  // — Remediation —
  "remediation.title": { en: "Targeted remediation", ar: "معالجة موجّهة" },
  "remediation.targets": { en: "Targets the root cause", ar: "تستهدف السبب الجذري" },
  "remediation.generating": { en: "Preparing an exercise…", ar: "جارٍ تحضير تمرين…" },
  "remediation.preview": { en: "Exercise preview", ar: "معاينة التمرين" },
  "remediation.assign": { en: "Assign to student", ar: "إسناد إلى الطالب" },
  "remediation.assigned": { en: "Assigned ✓", ar: "تمّ الإسناد ✓" },
  "remediation.none": {
    en: "No ready exercise for this skill yet.",
    ar: "لا يوجد تمرين جاهز لهذه المهارة بعد.",
  },

  // — Tuteur causal (Mouvement 04) —
  "tutor.why": { en: "Why this exercise?", ar: "لماذا هذا التمرين؟" },
  "tutor.hide": { en: "Hide", ar: "إخفاء" },
  "tutor.loading": { en: "Thinking it through…", ar: "جارٍ التفكير…" },
  "tutor.steps": { en: "Step by step", ar: "خطوة بخطوة" },
  "tutor.governance": {
    en: "Explained from the skill graph — no student data, no guesswork.",
    ar: "مشروح من خريطة المهارات — دون بيانات الطالب، دون تخمين.",
  },

  // — Parti pris éthique : pas de streak, pas de classement (Mouvement 04, À REFUSER) —
  "ethics.title": { en: "No streaks. No leaderboards. By design.", ar: "لا سلاسل. لا تصنيفات. عن قصد." },
  "ethics.body": {
    en: "Atlas measures to help, never to hook. We don't rank children against each other or guilt them into daily streaks — a deliberate choice for a tool used by minors.",
    ar: "أطلس يقيس ليساعد، لا ليُدمن. لا نُصنّف الأطفال بعضهم ضد بعض ولا نضغط عليهم بسلاسل يومية — اختيار متعمّد لأداة يستخدمها قُصّر.",
  },
  "ethics.governance.title": { en: "AI governance", ar: "حوكمة الذكاء الاصطناعي" },
  "ethics.governance.body": {
    en: "Anonymised prompts, structured outputs, zero student PII, human validation — and no manipulative retention mechanics.",
    ar: "مطالبات مجهولة، مخرجات منظَّمة، صفر بيانات تعريف للطالب، تحقّق بشري — وبلا آليات إبقاء تلاعبية.",
  },

  // — Student session —
  "session.start": { en: "Start a session", ar: "ابدأ جلسة" },
  "session.start.body": {
    en: "Short questions that adapt to you. Take your time — mistakes help us help you.",
    ar: "أسئلة قصيرة تتكيّف معك. خذ وقتك — الأخطاء تساعدنا على مساعدتك.",
  },
  "session.begin": { en: "Let's begin", ar: "لنبدأ" },
  "session.correct": { en: "Nicely done!", ar: "أحسنت!" },
  "session.incorrect": { en: "Good try — let's keep going.", ar: "محاولة جيدة — لنكمل." },
  "session.next": { en: "Next question", ar: "السؤال التالي" },
  "session.submit": { en: "Submit", ar: "إرسال" },
  "session.your.answer": { en: "Your answer", ar: "إجابتك" },
  "session.progress": { en: "Question", ar: "سؤال" },
  "session.done.title": { en: "Session complete", ar: "اكتملت الجلسة" },
  "session.done.body": {
    en: "Great work today. Here's what you practised.",
    ar: "عمل رائع اليوم. هذا ما تدرّبت عليه.",
  },
  "session.done.practised": { en: "Skills you practised", ar: "مهارات تدرّبت عليها" },
  "session.done.again": { en: "Practise again", ar: "تدرّب مرة أخرى" },

  // — Admin: school —
  "school.title": { en: "School overview", ar: "نظرة عامة على المدرسة" },
  "school.subtitle": {
    en: "Aggregate mastery across classes and skills — for steering and reporting.",
    ar: "إتقان مُجمَّع عبر الصفوف والمهارات — للقيادة وإعداد التقارير.",
  },
  "school.kpi.students": { en: "Students", ar: "الطلاب" },
  "school.kpi.classes": { en: "Classes", ar: "الصفوف" },
  "school.kpi.skills": { en: "Skills measured", ar: "مهارات مقيسة" },
  "school.kpi.mastery": { en: "Avg. mastery rate", ar: "متوسّط معدّل الإتقان" },
  "school.byskill": { en: "Mastery by skill (weakest first)", ar: "الإتقان حسب المهارة (الأضعف أولًا)" },
  "school.byclass": { en: "By class", ar: "حسب الصف" },
  "school.masteryrate": { en: "mastery rate", ar: "معدّل الإتقان" },

  // — Admin: classes & licences —
  "classes.title": { en: "Classes & licences", ar: "الصفوف والتراخيص" },
  "classes.subtitle": {
    en: "Provision classes, assign licences, invite teachers and students.",
    ar: "تجهيز الصفوف، إسناد التراخيص، دعوة المعلّمين والطلاب.",
  },
  "classes.add": { en: "New class", ar: "صفّ جديد" },
  "classes.licences": { en: "Licences", ar: "التراخيص" },
  "classes.used": { en: "used", ar: "مستخدَمة" },
  "classes.invite": { en: "Invite", ar: "دعوة" },
  "classes.col.name": { en: "Class", ar: "الصف" },
  "classes.col.students": { en: "Students", ar: "الطلاب" },
  "classes.col.avg": { en: "Avg. level", ar: "متوسّط المستوى" },

  // — Admin: report —
  "report.title": { en: "Outcomes report", ar: "تقرير المخرجات" },
  "report.subtitle": {
    en: "A shareable summary for families and the regulator.",
    ar: "ملخّص قابل للمشاركة للعائلات والجهة المنظِّمة.",
  },
  "report.print": { en: "Print / export PDF", ar: "طباعة / تصدير PDF" },
  "report.generated": { en: "Generated", ar: "أُنشئ في" },

  // — Surfaces de preuve (Mouvement 03) —
  "proof.title": { en: "Proof of impact", ar: "دليل الأثر" },
  "proof.subtitle": {
    en: "Measured gains over the last {n} days — before vs after.",
    ar: "مكاسب مَقيسة خلال {n} يومًا — قبل مقابل بعد.",
  },
  "proof.before": { en: "Before", ar: "قبل" },
  "proof.after": { en: "After", ar: "بعد" },
  "proof.cohort": { en: "Cohort success rate", ar: "معدّل نجاح الفوج" },
  "proof.gains": { en: "Biggest mastery gains", ar: "أكبر مكاسب الإتقان" },
  "proof.trajectory": { en: "Cohort trajectory (by level)", ar: "مسار الفوج (حسب المستوى)" },
  "proof.nodata": {
    en: "Not enough data yet — proof surfaces fill in as the cohort answers.",
    ar: "البيانات غير كافية بعد — تمتلئ أسطح الدليل مع إجابات الفوج.",
  },
  "proof.honest": {
    en: "Period-over-period, explicit window. Aggregated — no student identification.",
    ar: "مقارنة بين فترتين بنافذة صريحة. مُجمَّع — دون تعريف الطلاب.",
  },

  // — Parent —
  "parent.title": { en: "Your child's trajectory", ar: "مسار طفلك" },
  "parent.ontrack": { en: "On track for", ar: "على المسار نحو" },
  "parent.position": {
    en: "Where your child stands vs. higher-education expectations",
    ar: "أين يقف طفلك مقارنةً بتوقّعات التعليم العالي",
  },
  "parent.closing": { en: "Skills being strengthened", ar: "مهارات قيد التعزيز" },
  "parent.mastered.count": { en: "skills mastered", ar: "مهارات مُتقَنة" },
  "parent.reassure": {
    en: "The school is actively working on the next steps below.",
    ar: "تعمل المدرسة بنشاط على الخطوات التالية أدناه.",
  },
  // — Parent : action 10 min à la maison (Mouvement 01) —
  "parent.nextstep.title": { en: "One thing to try at home", ar: "شيء واحد لتجربته في المنزل" },
  "parent.nextstep.minutes": { en: "about {n} min", ar: "نحو {n} دقيقة" },
  "parent.nextstep.focus": { en: "Focus skill", ar: "المهارة المستهدفة" },
  "parent.nextstep.intro": {
    en: "A short, friendly activity that helps the most right now — no pressure, no score.",
    ar: "نشاط قصير وودود يساعد أكثر شيء الآن — بلا ضغط، بلا درجات.",
  },
  "parent.nextstep.example": { en: "Try this together", ar: "جرّبا هذا معًا" },
  "parent.nextstep.noexample": {
    en: "Ask your child to explain this skill to you — teaching it is great practice.",
    ar: "اطلب من طفلك أن يشرح لك هذه المهارة — شرحها تدريب ممتاز.",
  },

  // — Enseignant : digest hebdomadaire (Mouvement 01) —
  "digest.title": { en: "This week", ar: "هذا الأسبوع" },
  "digest.active": { en: "active students", ar: "طلاب نشطون" },
  "digest.answers": { en: "answers", ar: "إجابات" },
  "digest.priority": { en: "Priority this week", ar: "أولوية هذا الأسبوع" },
  "digest.emerging": { en: "Emerging gaps", ar: "ثغرات ناشئة" },
  "digest.emerging.hint": {
    en: "Newly measured below mastery in the last {n} days.",
    ar: "قِيست حديثًا دون الإتقان خلال {n} أيام.",
  },
  "digest.quiet": {
    en: "A quiet week — no new gaps emerged.",
    ar: "أسبوع هادئ — لم تظهر ثغرات جديدة.",
  },

  // — IT —
  "it.title": { en: "Security & identity", ar: "الأمن والهوية" },
  "it.subtitle": {
    en: "Authentication, MFA and data-residency posture. Purchase gate — kept minimal.",
    ar: "المصادقة وMFA وموقع إقامة البيانات. بوّابة الشراء — مُبقاة بالحدّ الأدنى.",
  },
  "it.sso": { en: "Single sign-on (SSO)", ar: "الدخول الموحّد (SSO)" },
  "it.mfa": { en: "Multi-factor authentication", ar: "المصادقة متعدّدة العوامل" },
  "it.residency": { en: "Data residency", ar: "إقامة البيانات" },
  "it.audit": { en: "Audit logging", ar: "تسجيل التدقيق" },
  "it.enabled": { en: "Enabled", ar: "مُفعّل" },
  "it.required": { en: "Required for staff", ar: "مطلوب للطاقم" },
  "it.configurable": { en: "Configurable", ar: "قابل للتهيئة" },

  // — Console rostering (Phase D) —
  "it.rostering": { en: "Directory sync (Google Workspace)", ar: "مزامنة الدليل (Google Workspace)" },
  "it.security": { en: "Security posture", ar: "الوضع الأمني" },
  "it.domain": { en: "Domain", ar: "النطاق" },
  "it.lastsync": { en: "Last sync", ar: "آخر مزامنة" },
  "it.seats": { en: "Seats used", ar: "المقاعد المستخدمة" },
  "it.admin": { en: "Admin", ar: "المسؤول" },
  "it.never": { en: "Never", ar: "أبدًا" },
  "it.sync": { en: "Sync now", ar: "زامن الآن" },
  "it.syncing": { en: "Syncing…", ar: "جارٍ المزامنة…" },
  "it.runs": { en: "Sync history", ar: "سجل المزامنة" },
  "it.noruns": { en: "No sync yet.", ar: "لا توجد مزامنة بعد." },
  "it.loaderror": { en: "Could not load integration.", ar: "تعذّر تحميل التكامل." },
  "it.syncerror": { en: "Sync failed. Check the integration.", ar: "فشلت المزامنة. تحقّق من التكامل." },
  "it.status.pending": { en: "Pending", ar: "قيد الانتظار" },
  "it.status.connected": { en: "Connected", ar: "متّصل" },
  "it.status.error": { en: "Error", ar: "خطأ" },
  "it.status.over": { en: "Over capacity", ar: "تجاوز السعة" },
  "it.status.blocked": { en: "Blocked", ar: "محظور" },
  "it.overcap": { en: "license exceeded", ar: "تجاوز الترخيص" },
  "it.blocked.title": { en: "Mass change held for review", ar: "تغيير جماعي محجوز للمراجعة" },
  "it.blocked.body": {
    en: "This sync would deactivate {n} people — held as a safety measure. Additions were applied; removals await your approval.",
    ar: "ستؤدي هذه المزامنة إلى تعطيل {n} شخصًا — تم حجزها كإجراء وقائي. طُبّقت الإضافات؛ وتنتظر عمليات الإزالة موافقتك.",
  },
  "it.blocked.approve": { en: "Approve & apply removals", ar: "الموافقة وتطبيق الإزالة" },
  "it.setup": { en: "Getting started", ar: "بدء الاستخدام" },
  "it.invite": { en: "Invite now", ar: "دعوة الآن" },
  "it.step.connect": { en: "Connect Google Workspace", ar: "ربط Google Workspace" },
  "it.step.sync": { en: "Run first roster sync", ar: "تشغيل أول مزامنة" },
  "it.step.verify": { en: "Verify enrolment numbers", ar: "التحقّق من الأعداد" },
  "it.step.parents": { en: "Invite parents", ar: "دعوة أولياء الأمور" },
  "parent.child": { en: "Child", ar: "الطفل" },
  "guardians.title": { en: "Parents / guardians", ar: "أولياء الأمور" },
  "guardians.hint": {
    en: "Link a parent's email to give them read-only access to this child.",
    ar: "اربط بريد ولي الأمر لمنحه وصولاً للقراءة فقط لهذا الطفل.",
  },
  "guardians.placeholder": { en: "parent@email.com", ar: "parent@email.com" },
  "guardians.add": { en: "Link", ar: "ربط" },
  "guardians.remove": { en: "Remove", ar: "إزالة" },
  "guardians.staff": { en: "staff", ar: "طاقم" },
  "guardians.roster": { en: "Classroom", ar: "Classroom" },
  "it.col.date": { en: "Date", ar: "التاريخ" },
  "it.col.created": { en: "Created", ar: "أُنشئ" },
  "it.col.updated": { en: "Updated", ar: "حُدّث" },
  "it.col.deactivated": { en: "Deactivated", ar: "عُطّل" },
  "it.col.errors": { en: "Errors", ar: "أخطاء" },
  // — Console linguiste : descente de l'arabe (Mouvement 02) —
  "ar.title": { en: "Arabic content review", ar: "مراجعة المحتوى العربي" },
  "ar.subtitle": {
    en: "Bring Arabic down into the items themselves — machine proposes, you validate.",
    ar: "أنزِل العربية إلى داخل الأسئلة نفسها — الآلة تقترح، وأنت تُصادق.",
  },
  "ar.coverage": { en: "Validated Arabic coverage", ar: "تغطية العربية المُصادَقة" },
  "ar.coverage.of": { en: "of {n} items", ar: "من {n} سؤالًا" },
  "ar.pending.title": { en: "Awaiting Arabic", ar: "بانتظار العربية" },
  "ar.en": { en: "English", ar: "الإنجليزية" },
  "ar.ar": { en: "Arabic", ar: "العربية" },
  "ar.propose": { en: "Propose translation", ar: "اقترح ترجمة" },
  "ar.proposing": { en: "Translating…", ar: "جارٍ الترجمة…" },
  "ar.validate": { en: "Validate Arabic", ar: "صادِق على العربية" },
  "ar.math.ok": { en: "Numbers preserved", ar: "الأرقام محفوظة" },
  "ar.math.warn": { en: "Check the numbers", ar: "تحقّق من الأرقام" },
  "ar.none": { en: "Nothing awaiting Arabic. 🎉", ar: "لا شيء بانتظار العربية. 🎉" },
  "ar.notyet": { en: "No Arabic proposed yet.", ar: "لم تُقترَح العربية بعد." },

  "it.compliance": { en: "Compliance & audit", ar: "الامتثال والتدقيق" },
  "it.export": { en: "Export data", ar: "تصدير البيانات" },
  "it.noaudit": { en: "No audit entries yet.", ar: "لا توجد سجلات تدقيق بعد." },

  // — Vue curriculaire (Lot B, B3) : console IT + badges standards —
  "curriculum.title": { en: "Curriculum view", ar: "عرض المنهج" },
  "curriculum.hint": {
    en: "Standards framework shown across teacher and school views. Atlas = neutral view, no standard labels.",
    ar: "إطار المعايير المعروض في شاشات المعلّم والمدرسة. أطلس = عرض محايد، دون رموز معايير.",
  },
  "curriculum.current": { en: "Active", ar: "الفعّال" },
  "curriculum.select": { en: "Displayed framework", ar: "الإطار المعروض" },
  "curriculum.fw.atlas": { en: "Atlas (neutral)", ar: "أطلس (محايد)" },
  "curriculum.fw.ccssm": { en: "Common Core (CCSS-M)", ar: "المعايير الأمريكية (CCSS-M)" },
  "curriculum.fw.uknc": { en: "UK National Curriculum", ar: "المنهج الوطني البريطاني" },
  "curriculum.fw.moe": { en: "MoE UAE", ar: "وزارة التربية والتعليم (الإمارات)" },
  "curriculum.error": { en: "Could not update the curriculum view.", ar: "تعذّر تحديث عرض المنهج." },

  // — Couverture du programme (Lot B, B5 / D-B5) : rapport école —
  "coverage.title": { en: "Curriculum coverage", ar: "تغطية المنهج" },
  "coverage.mastered": { en: "aligned skills mastered", ar: "مهارات متوافقة مُتقَنة" },
  "coverage.covered": { en: "Covered", ar: "مُغطًّى" },
  "coverage.threshold": { en: "cohort mastery threshold", ar: "عتبة إتقان الفوج" },
  "coverage.note": {
    en: "Covered = every exactly-aligned skill mastered at cohort level — never claimed for individual students.",
    ar: "مُغطًّى = إتقان كل المهارات المتوافقة تمامًا على مستوى الفوج — لا يُدَّعى ذلك أبدًا لطالب بعينه.",
  },

  // — Back-office linguiste (persona dédié) : file de validation AR —
  "ling.login.title": { en: "Linguist review access", ar: "دخول المراجع اللغوي" },
  "ling.login.intro": {
    en: "Enter your Atlas email — we'll send you a one-time sign-in link.",
    ar: "أدخل بريد أطلس الخاص بك — سنرسل لك رابط دخول لمرة واحدة.",
  },
  "ling.login.submit": { en: "Send me a link", ar: "أرسل لي رابطًا" },
  "ling.login.sent.title": { en: "Check your inbox", ar: "تحقّق من بريدك" },
  "ling.login.sent.body": {
    en: "If that email can review Arabic, a sign-in link is on its way.",
    ar: "إذا كان بإمكان هذا البريد مراجعة العربية، فإن رابط الدخول في طريقه إليك.",
  },
  "ling.title": { en: "Arabic review queue", ar: "قائمة مراجعة العربية" },
  "ling.subtitle": {
    en: "Review, correct and validate the Arabic translation of each item. Machine translates, you decide.",
    ar: "راجِع وصحِّح وصادِق على الترجمة العربية لكل سؤال. الآلة تُترجم، وأنت تُقرِّر.",
  },
  "ling.remaining": { en: "{n} left to review", ar: "بقي {n} للمراجعة" },
  "ling.en": { en: "English (source)", ar: "الإنجليزية (المصدر)" },
  "ling.ar": { en: "Arabic (to validate)", ar: "العربية (للمصادقة)" },
  "ling.answer": { en: "Answer", ar: "الإجابة" },
  "ling.options": { en: "Options", ar: "الخيارات" },
  "ling.math.warn": { en: "math ⚠️", ar: "الأرقام ⚠️" },
  "ling.math.ok": { en: "numbers preserved", ar: "الأرقام محفوظة" },
  "ling.edit": { en: "Edit Arabic", ar: "تعديل العربية" },
  "ling.save": { en: "Save correction", ar: "حفظ التصحيح" },
  "ling.saving": { en: "Saving…", ar: "جارٍ الحفظ…" },
  "ling.validate": { en: "Validate", ar: "مصادقة" },
  "ling.flag": { en: "Flag a problem", ar: "الإبلاغ عن مشكلة" },
  "ling.flag.reason": { en: "What's wrong with this translation?", ar: "ما الخطأ في هذه الترجمة؟" },
  "ling.flag.submit": { en: "Flag", ar: "إبلاغ" },
  "ling.cancel": { en: "Cancel", ar: "إلغاء" },
  "ling.flagged": { en: "Flagged", ar: "مُبلَّغ عنه" },
  "ling.none": { en: "Nothing left to validate. 🎉", ar: "لا شيء متبقٍّ للمصادقة. 🎉" },
  "ling.notyet": { en: "No Arabic yet — add a translation.", ar: "لا توجد عربية بعد — أضف ترجمة." },
} as const;

export type DictKey = keyof typeof DICT;

export function translate(key: DictKey, lang: Lang): string {
  const entry = DICT[key];
  return entry ? entry[lang] : (key as string);
}
