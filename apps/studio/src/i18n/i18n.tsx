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
  globalSearch: "Open governed enterprise search", searchPlaceholder: "Search authorized entities", searchAction: "Search",
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
  searchTitle: "Governed enterprise search", searchBody: "Find authorized entities by canonical ID, label, or alias using deterministic exact and prefix matching.",
  canonicalId: "Canonical entity identifier", canonicalIdPlaceholder: "Enter an exact entity ID", lookup: "Look up", exactLookupOnly: "Exact canonical ID only — labels, aliases, and partial text are not searched.", searching: "Searching authorized entities…",
  searchQueryLabel: "Search query", searchQueryPlaceholder: "Enter an entity ID, label, or alias", governedSearchHint: "Exact and beginning-prefix matches only. Search text stays out of the URL and browser storage.",
  searchReadyTitle: "Ready to search", searchReadyBody: "Enter an entity ID, label, or alias. Authorization is evaluated by the Knowledge Graph for every request.", searchTypingTitle: "Ready to submit", searchTypingBody: "Submit when your search text is ready. Studio does not alter its matching semantics.", noResultsTitle: "No authorized results", noResultsBody: "No authorized entities matched this search.", searchUnavailable: "Search unavailable", openEntity: "Open entity workspace",
  invalidSearchTitle: "Check your search", invalidSearchBody: "Enter a valid bounded search query and try again.", sessionExpiredTitle: "Session expired", sessionExpiredBody: "Sign in again to continue searching securely.",
  authorizedResults: "Authorized search results", resultsAvailable: "Authorized search results are available.", revisionContext: "Pinned revision", loadMore: "Load more", loadingMore: "Loading more authorized results…", continuationUnavailableTitle: "Continuation unavailable", continuationUnavailableBody: "This search continuation is no longer valid. Restart to search the current authorized revision.", restartSearch: "Restart search",
  matchIdExact: "Exact ID", matchLabelExact: "Exact label", matchAliasExact: "Exact alias", matchIdPrefix: "ID prefix", matchLabelPrefix: "Label prefix", matchAliasPrefix: "Alias prefix",
  exploreInGraph: "Explore in graph", graphExplorerTitle: "Knowledge Graph Explorer", graphExplorerBody: "Explore authorized relationships progressively from one selected entity. The visible graph is not a completeness statement.",
  rootDiscovery: "Root discovery", findGraphRoot: "Choose an authorized starting entity", findGraphRootBody: "Use governed search to select the canonical entity that anchors this exploration.", graphSearchPrivacy: "Search text remains in memory and is submitted only through the same-origin governed BFF route.", exploreEntity: "Explore entity",
  loadingGraphRoot: "Loading authorized graph root…", graphUnavailable: "Graph unavailable", graphControls: "Graph explorer controls", graphRoot: "Graph root", viewMode: "Explorer representation", graphView: "Graph view", relationshipList: "Relationship list", previousSelection: "Previous selection", chooseAnotherRoot: "Choose another root", graphWorkspace: "Authorized graph workspace", graphVisualization: "Authorized knowledge graph visualization",
  selectedEntity: "Selected entity", selectedEntityDetails: "Selected entity details", selectNodePrompt: "Select a visible entity to inspect its approved details.", selectedRelationship: "Selected relationship", relationshipId: "Relationship ID", relationshipType: "Relationship type", direction: "Direction",
  expandNode: "Expand entity", expandSelected: "Expand selected entity", expandingNode: "Expanding entity…", expandedNode: "Entity expanded", loadMoreRelationships: "Load more relationships", expansionUnavailable: "This entity expansion is unavailable. The visible graph remains unchanged.", graphViewLimit: "The presentation safety limit has been reached. Choose a new root to continue exploring.",
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
  globalSearch: "فتح البحث المؤسسي الخاضع للحوكمة", searchPlaceholder: "البحث في الكيانات المصرح بها", searchAction: "بحث",
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
  searchTitle: "البحث المؤسسي الخاضع للحوكمة", searchBody: "ابحث في الكيانات المصرح بها بالمعرّف الأساسي أو التسمية أو الاسم البديل باستخدام المطابقة التامة ومطابقة البادئة الحتمية.",
  canonicalId: "معرّف الكيان الأساسي", canonicalIdPlaceholder: "أدخل معرّف كيان مطابقاً", lookup: "بحث", exactLookupOnly: "المعرّف الأساسي المطابق فقط — لا يتم البحث في التسميات أو الأسماء البديلة أو النص الجزئي.", searching: "جارٍ البحث في الكيانات المصرح بها…",
  searchQueryLabel: "نص البحث", searchQueryPlaceholder: "أدخل معرّف كيان أو تسمية أو اسماً بديلاً", governedSearchHint: "المطابقة التامة ومطابقة بداية النص فقط. لا يُحفظ نص البحث في العنوان أو مساحة تخزين المتصفح.",
  searchReadyTitle: "جاهز للبحث", searchReadyBody: "أدخل معرّف كيان أو تسمية أو اسماً بديلاً. يعاد تقييم التفويض في الرسم البياني المعرفي لكل طلب.", searchTypingTitle: "جاهز للإرسال", searchTypingBody: "أرسل النص عندما يصبح جاهزاً. لا يغيّر الاستوديو دلالات المطابقة.", noResultsTitle: "لا توجد نتائج مصرح بها", noResultsBody: "لم تطابق كيانات مصرح بها نص البحث هذا.", searchUnavailable: "البحث غير متاح", openEntity: "فتح مساحة الكيان",
  invalidSearchTitle: "تحقق من البحث", invalidSearchBody: "أدخل نص بحث صالحاً ومحدوداً ثم حاول مجدداً.", sessionExpiredTitle: "انتهت الجلسة", sessionExpiredBody: "سجّل الدخول مجدداً لمتابعة البحث بأمان.",
  authorizedResults: "نتائج البحث المصرح بها", resultsAvailable: "نتائج البحث المصرح بها متاحة.", revisionContext: "المراجعة المثبتة", loadMore: "تحميل المزيد", loadingMore: "جارٍ تحميل المزيد من النتائج المصرح بها…", continuationUnavailableTitle: "المتابعة غير متاحة", continuationUnavailableBody: "لم تعد متابعة البحث هذه صالحة. أعد البحث في المراجعة الحالية المصرح بها.", restartSearch: "إعادة البحث",
  matchIdExact: "معرّف مطابق", matchLabelExact: "تسمية مطابقة", matchAliasExact: "اسم بديل مطابق", matchIdPrefix: "بادئة المعرّف", matchLabelPrefix: "بادئة التسمية", matchAliasPrefix: "بادئة الاسم البديل",
  exploreInGraph: "استكشاف في الرسم", graphExplorerTitle: "مستكشف الرسم البياني المعرفي", graphExplorerBody: "استكشف العلاقات المصرح بها تدريجياً بدءاً من كيان محدد. لا يمثل الرسم الظاهر اكتمال البيانات.",
  rootDiscovery: "اكتشاف نقطة البداية", findGraphRoot: "اختر كيان بداية مصرحاً به", findGraphRootBody: "استخدم البحث الخاضع للحوكمة لتحديد الكيان الأساسي الذي يبدأ منه الاستكشاف.", graphSearchPrivacy: "يبقى نص البحث في الذاكرة ويُرسل فقط عبر مسار BFF الخاضع للحوكمة ومن نفس المصدر.", exploreEntity: "استكشاف الكيان",
  loadingGraphRoot: "جارٍ تحميل نقطة بداية الرسم المصرح بها…", graphUnavailable: "الرسم غير متاح", graphControls: "عناصر تحكم مستكشف الرسم", graphRoot: "نقطة بداية الرسم", viewMode: "تمثيل المستكشف", graphView: "عرض الرسم", relationshipList: "قائمة العلاقات", previousSelection: "التحديد السابق", chooseAnotherRoot: "اختيار نقطة بداية أخرى", graphWorkspace: "مساحة الرسم المصرح بها", graphVisualization: "تصور الرسم البياني المعرفي المصرح به",
  selectedEntity: "الكيان المحدد", selectedEntityDetails: "تفاصيل الكيان المحدد", selectNodePrompt: "حدد كياناً ظاهراً لفحص تفاصيله المعتمدة.", selectedRelationship: "العلاقة المحددة", relationshipId: "معرّف العلاقة", relationshipType: "نوع العلاقة", direction: "الاتجاه",
  expandNode: "توسيع الكيان", expandSelected: "توسيع الكيان المحدد", expandingNode: "جارٍ توسيع الكيان…", expandedNode: "تم توسيع الكيان", loadMoreRelationships: "تحميل المزيد من العلاقات", expansionUnavailable: "توسيع هذا الكيان غير متاح. يبقى الرسم الظاهر دون تغيير.", graphViewLimit: "تم بلوغ حد العرض الآمن. اختر نقطة بداية جديدة لمتابعة الاستكشاف.",
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
