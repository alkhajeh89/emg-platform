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
  globalSearch: "Global search", searchPlaceholder: "Search EMG workspaces", searchAction: "Open search workspace",
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
  globalSearch: "البحث العام", searchPlaceholder: "البحث في مساحات عمل EMG", searchAction: "فتح مساحة البحث",
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
