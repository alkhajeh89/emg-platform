"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "en" | "ar";

const en = {
  brand: "EMG Studio", brandHome: "EMG Studio home", english: "English", arabic: "العربية", language: "Language",
  secureWorkspace: "Secure workspace", loginTitle: "Connect to EMG Studio",
  loginBody: "Sign in through the platform identity boundary. Credentials and tokens never enter this application.",
  loginAction: "Continue to secure sign in", protectedBy: "Browser session protected by Studio BFF",
  authenticated: "Authenticated session", logout: "Sign out", logoutFailed: "Sign out failed. Your session remains active.",
  checkingSession: "Checking secure session…", studioUnavailable: "Studio is unavailable",
  sessionUnavailable: "The secure session service could not be reached.", retry: "Try again",
  openNavigation: "Open navigation", closeNavigation: "Close navigation", primaryNavigation: "Primary navigation", skipContent: "Skip to content",
  globalSearch: "Entity lookup", searchPlaceholder: "Canonical entity ID", searchAction: "Look up entity",
  currentSection: "Current section", dashboard: "Dashboard", search: "Search", knowledgeGraph: "Knowledge Graph",
  entities: "Entities", evidence: "Evidence", timeline: "Timeline", decisions: "Decisions",
  dashboardEyebrow: "Enterprise workspace", dashboardTitle: "Welcome to EMG Studio",
  dashboardBody: "A secure workspace for exploring governed enterprise knowledge through the Studio BFF boundary.",
  workspaceOverview: "Workspace overview", platformStatus: "Platform status", platformAvailable: "Studio session available",
  platformStatusBody: "Authentication and the secure browser boundary are active. Operational service metrics are not exposed by an approved dashboard API.",
  securityContext: "Security context", securityContextBody: "Your browser uses an opaque server-side session. Authorization remains enforced by downstream services.",
  quickActions: "Quick actions", explorePilot: "Explore pilot entity", openEntities: "Open entity workspace",
  openSearch: "Open search", viewKnowledgeGraph: "View knowledge workspace", recentActivity: "Recent workspace activity",
  noActivityTitle: "No activity feed available", noActivityBody: "A governed activity API is not available in Sprint 1. No events or counts are fabricated.",
  workspaceShortcuts: "Knowledge workspace shortcuts", planned: "Planned", available: "Available",
  backendData: "Backend-derived", staticNavigation: "Navigation", intentionallyUnavailable: "Not yet available",
  plannedWorkspace: "Planned workspace", plannedBody: "This route establishes enterprise navigation. Its product capability and backend integration are not part of Sprint 1.",
  returnDashboard: "Return to dashboard", entityWorkspace: "Entity workspace", entityWorkspaceBody: "Retrieve an authorized entity through the existing delegated Studio BFF read boundary.",
  entityId: "Entity identifier", explore: "Explore entity", pilotEntity: "Pilot entity", loadingEntity: "Loading authorized entity…",
  readyTitle: "Ready to explore", readyBody: "Enter an entity identifier to retrieve its current authorized view.",
  unavailableTitle: "Entity unavailable", notFound: "No authorized entity matched that identifier.",
  requestFailed: "The request could not be completed. Try again when the platform is available.",
  confidence: "Confidence", revision: "Revision", source: "Source", notSpecified: "Not specified",
  properties: "Properties", noProperties: "No additional properties are available.", aliases: "Aliases",
  noAliases: "No aliases recorded", evidenceLabel: "Evidence", linkedRecord: "linked record", linkedRecords: "linked records",
  entityType: "Entity type", platform: "EMG Platform", boundary: "Browser → Studio BFF → Authorized services",
  searchTitle: "Entity lookup", searchBody: "Retrieve an authorized entity by its exact canonical identifier. Free-text and relevance-ranked search are not available through an approved contract.",
  canonicalId: "Canonical entity identifier", canonicalIdPlaceholder: "Enter an exact entity ID", lookup: "Look up", exactLookupOnly: "Exact canonical ID only — labels, aliases, and partial text are not searched.", searching: "Looking up authorized entity…",
  searchReadyTitle: "Ready for an exact lookup", searchReadyBody: "Enter a canonical entity identifier. The request is authorized by the Knowledge Graph service.", noResultsTitle: "No authorized result", noResultsBody: "No authorized entity matched that exact canonical identifier.", searchUnavailable: "Lookup unavailable", openEntity: "Open entity workspace",
  canonicalLookupHint: "Canonical identifiers are case-sensitive and are safely encoded in the URL.", identity: "Identity", createdAt: "Created", updatedAt: "Updated", revisionCommitted: "Revision committed", locator: "Locator", capturedAt: "Captured", noEvidence: "No evidence references are returned for this entity.", relationships: "Relationships", noRelationships: "No authorized relationships are returned for this entity.", relationshipsUnavailable: "Relationship data could not be loaded; the entity view remains available.", moreRelationshipsAvailable: "More authorized relationships exist. Relationship pagination is not yet exposed in this workspace.", history: "History", noHistory: "No temporal histories are returned for this entity.", current: "current",
} as const;

const ar: Record<keyof typeof en, string> = {
  brand: "استوديو EMG", brandHome: "الصفحة الرئيسية لاستوديو EMG", english: "English", arabic: "العربية", language: "اللغة",
  secureWorkspace: "مساحة عمل آمنة", loginTitle: "الاتصال باستوديو EMG",
  loginBody: "سجّل الدخول عبر بوابة هوية المنصة. لا تدخل بيانات الاعتماد أو الرموز إلى هذا التطبيق.",
  loginAction: "المتابعة إلى تسجيل الدخول الآمن", protectedBy: "جلسة المتصفح محمية بواسطة Studio BFF",
  authenticated: "جلسة موثّقة", logout: "تسجيل الخروج", logoutFailed: "فشل تسجيل الخروج. ما زالت جلستك نشطة.",
  checkingSession: "جارٍ التحقق من الجلسة الآمنة…", studioUnavailable: "الاستوديو غير متاح",
  sessionUnavailable: "تعذر الوصول إلى خدمة الجلسة الآمنة.", retry: "إعادة المحاولة",
  openNavigation: "فتح التنقل", closeNavigation: "إغلاق التنقل", primaryNavigation: "التنقل الرئيسي", skipContent: "التخطي إلى المحتوى",
  globalSearch: "البحث عن كيان", searchPlaceholder: "معرّف الكيان الأساسي", searchAction: "البحث عن الكيان",
  currentSection: "القسم الحالي", dashboard: "لوحة المعلومات", search: "البحث", knowledgeGraph: "الرسم البياني المعرفي",
  entities: "الكيانات", evidence: "الأدلة", timeline: "الخط الزمني", decisions: "القرارات",
  dashboardEyebrow: "مساحة عمل مؤسسية", dashboardTitle: "مرحباً بك في استوديو EMG",
  dashboardBody: "مساحة آمنة لاستكشاف المعرفة المؤسسية الخاضعة للحوكمة عبر بوابة Studio BFF.",
  workspaceOverview: "نظرة عامة على مساحة العمل", platformStatus: "حالة المنصة", platformAvailable: "جلسة الاستوديو متاحة",
  platformStatusBody: "المصادقة وحدود المتصفح الآمنة نشطة. لا تعرض واجهة لوحة معلومات معتمدة مقاييس تشغيل الخدمات.",
  securityContext: "سياق الأمان", securityContextBody: "يستخدم متصفحك جلسة مبهمة على الخادم. تظل الخدمات الخلفية مسؤولة عن التفويض.",
  quickActions: "إجراءات سريعة", explorePilot: "استعراض كيان التجربة", openEntities: "فتح مساحة الكيانات",
  openSearch: "فتح البحث", viewKnowledgeGraph: "عرض مساحة المعرفة", recentActivity: "نشاط مساحة العمل الأخير",
  noActivityTitle: "لا يتوفر موجز نشاط", noActivityBody: "لا تتوفر واجهة نشاط خاضعة للحوكمة في Sprint 1. لا يتم اختلاق أحداث أو أعداد.",
  workspaceShortcuts: "اختصارات مساحة المعرفة", planned: "مخطط", available: "متاح",
  backendData: "مستمد من الخلفية", staticNavigation: "تنقل", intentionallyUnavailable: "غير متاح بعد",
  plannedWorkspace: "مساحة عمل مخططة", plannedBody: "يثبت هذا المسار التنقل المؤسسي. قدرته واتصاله بالخلفية ليسا ضمن Sprint 1.",
  returnDashboard: "العودة إلى لوحة المعلومات", entityWorkspace: "مساحة عمل الكيانات", entityWorkspaceBody: "استرجع كياناً مصرحاً به عبر بوابة القراءة المفوضة الحالية في Studio BFF.",
  entityId: "معرّف الكيان", explore: "استعراض الكيان", pilotEntity: "كيان التجربة", loadingEntity: "جارٍ تحميل الكيان المصرح به…",
  readyTitle: "جاهز للاستعراض", readyBody: "أدخل معرّف كيان لاسترجاع عرضه الحالي المصرح به.",
  unavailableTitle: "الكيان غير متاح", notFound: "لم يتم العثور على كيان مصرح به يطابق هذا المعرّف.",
  requestFailed: "تعذر إكمال الطلب. حاول مجدداً عند توفر المنصة.",
  confidence: "الثقة", revision: "المراجعة", source: "المصدر", notSpecified: "غير محدد",
  properties: "الخصائص", noProperties: "لا توجد خصائص إضافية متاحة.", aliases: "الأسماء البديلة",
  noAliases: "لا توجد أسماء بديلة مسجلة", evidenceLabel: "الأدلة", linkedRecord: "سجل مرتبط", linkedRecords: "سجلات مرتبطة",
  entityType: "نوع الكيان", platform: "منصة EMG", boundary: "المتصفح ← Studio BFF ← الخدمات المصرح بها",
  searchTitle: "البحث عن كيان", searchBody: "استرجع كياناً مصرحاً به باستخدام معرّفه الأساسي المطابق تماماً. لا يتوفر بحث نصي حر أو ترتيب حسب الصلة عبر عقد معتمد.",
  canonicalId: "معرّف الكيان الأساسي", canonicalIdPlaceholder: "أدخل معرّف كيان مطابقاً", lookup: "بحث", exactLookupOnly: "المعرّف الأساسي المطابق فقط — لا يتم البحث في التسميات أو الأسماء البديلة أو النص الجزئي.", searching: "جارٍ البحث عن الكيان المصرح به…",
  searchReadyTitle: "جاهز للبحث المطابق", searchReadyBody: "أدخل معرّف كيان أساسياً. تصرّح خدمة الرسم البياني المعرفي بالطلب.", noResultsTitle: "لا توجد نتيجة مصرح بها", noResultsBody: "لم يطابق أي كيان مصرح به ذلك المعرّف الأساسي تماماً.", searchUnavailable: "البحث غير متاح", openEntity: "فتح مساحة الكيان",
  canonicalLookupHint: "معرّفات الكيانات حساسة لحالة الأحرف ويتم ترميزها بأمان في عنوان URL.", identity: "الهوية", createdAt: "تاريخ الإنشاء", updatedAt: "تاريخ التحديث", revisionCommitted: "اعتماد المراجعة", locator: "الموقع", capturedAt: "تاريخ الالتقاط", noEvidence: "لا توجد مراجع أدلة مسترجعة لهذا الكيان.", relationships: "العلاقات", noRelationships: "لا توجد علاقات مصرح بها مسترجعة لهذا الكيان.", relationshipsUnavailable: "تعذر تحميل بيانات العلاقات؛ لا يزال عرض الكيان متاحاً.", moreRelationshipsAvailable: "توجد علاقات مصرح بها إضافية. لم تُتح إتاحة صفحات العلاقات في مساحة العمل بعد.", history: "السجل التاريخي", noHistory: "لا توجد سجلات زمنية مسترجعة لهذا الكيان.", current: "الحالي",
};

const messages = { en, ar };
export type MessageKey = keyof typeof en;
const I18nContext = createContext<{ locale: Locale; setLocale: (locale: Locale) => void; t: (key: MessageKey) => string } | null>(null);

export function I18nProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [locale, setLocale] = useState<Locale>("en");
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
  }, [locale]);
  const value = useMemo(() => ({ locale, setLocale, t: (key: MessageKey) => messages[locale][key] }), [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used within I18nProvider");
  return context;
}
