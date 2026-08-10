"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "en" | "ar";

const messages = {
  en: {
    brand: "EMG Studio", brandHome: "EMG Studio home", english: "English", arabic: "العربية", secureWorkspace: "Secure workspace",
    loginTitle: "Connect to EMG Studio",
    loginBody: "Sign in through the platform identity boundary. Credentials and tokens never enter this application.",
    loginAction: "Continue to secure sign in", protectedBy: "Browser session protected by Studio BFF",
    authenticated: "Authenticated session", logout: "Sign out", knowledgeGraph: "Knowledge Graph",
    heroLine1: "Find the signal.", heroLine2: "Keep the context.",
    heroBody: "Inspect an authorized entity through the delegated Studio BFF read boundary.",
    entityId: "Entity identifier", explore: "Explore entity", pilotEntity: "Pilot entity",
    loadingEntity: "Loading authorized entity…", readyTitle: "Ready to explore",
    readyBody: "Enter an entity identifier to retrieve its current authorized view.", unavailableTitle: "Entity unavailable",
    notFound: "No authorized entity matched that identifier.", requestFailed: "The request could not be completed. Try again when the platform is available.",
    confidence: "Confidence", revision: "Revision", source: "Source", notSpecified: "Not specified",
    properties: "Properties", noProperties: "No additional properties are available.", aliases: "Aliases",
    noAliases: "No aliases recorded", evidence: "Evidence", linkedRecord: "linked record", linkedRecords: "linked records",
    checkingSession: "Checking secure session…", studioUnavailable: "Studio is unavailable",
    sessionUnavailable: "The secure session service could not be reached.", retry: "Try again",
    logoutFailed: "Sign out failed. Your session remains active.", platform: "EMG Platform",
    boundary: "Browser → Studio BFF → Authorized services", language: "Language",
    entityType: "Entity type",
  },
  ar: {
    brand: "استوديو EMG", brandHome: "الصفحة الرئيسية لاستوديو EMG", english: "English", arabic: "العربية", secureWorkspace: "مساحة عمل آمنة",
    loginTitle: "الاتصال باستوديو EMG",
    loginBody: "سجّل الدخول عبر بوابة هوية المنصة. لا تدخل بيانات الاعتماد أو الرموز إلى هذا التطبيق.",
    loginAction: "المتابعة إلى تسجيل الدخول الآمن", protectedBy: "جلسة المتصفح محمية بواسطة Studio BFF",
    authenticated: "جلسة موثّقة", logout: "تسجيل الخروج", knowledgeGraph: "الرسم البياني المعرفي",
    heroLine1: "اعثر على الإشارة.", heroLine2: "واحتفظ بالسياق.",
    heroBody: "استعرض كياناً مصرحاً به عبر بوابة القراءة المفوضة في Studio BFF.",
    entityId: "معرّف الكيان", explore: "استعراض الكيان", pilotEntity: "كيان التجربة",
    loadingEntity: "جارٍ تحميل الكيان المصرح به…", readyTitle: "جاهز للاستعراض",
    readyBody: "أدخل معرّف كيان لاسترجاع عرضه الحالي المصرح به.", unavailableTitle: "الكيان غير متاح",
    notFound: "لم يتم العثور على كيان مصرح به يطابق هذا المعرّف.", requestFailed: "تعذر إكمال الطلب. حاول مجدداً عند توفر المنصة.",
    confidence: "الثقة", revision: "المراجعة", source: "المصدر", notSpecified: "غير محدد",
    properties: "الخصائص", noProperties: "لا توجد خصائص إضافية متاحة.", aliases: "الأسماء البديلة",
    noAliases: "لا توجد أسماء بديلة مسجلة", evidence: "الأدلة", linkedRecord: "سجل مرتبط", linkedRecords: "سجلات مرتبطة",
    checkingSession: "جارٍ التحقق من الجلسة الآمنة…", studioUnavailable: "الاستوديو غير متاح",
    sessionUnavailable: "تعذر الوصول إلى خدمة الجلسة الآمنة.", retry: "إعادة المحاولة",
    logoutFailed: "فشل تسجيل الخروج. ما زالت جلستك نشطة.", platform: "منصة EMG",
    boundary: "المتصفح ← Studio BFF ← الخدمات المصرح بها", language: "اللغة",
    entityType: "نوع الكيان",
  },
} as const;

export type MessageKey = keyof typeof messages.en;
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
