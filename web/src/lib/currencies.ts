/**
 * Currency options shared by the Profile setting and the result-page switcher.
 * Codes are ISO 4217; the Frankfurter FX endpoint the agents use covers these.
 */
export interface CurrencyOption {
  value: string;
  label: string;
}

export const CURRENCIES: CurrencyOption[] = [
  { value: "MYR", label: "MYR — Malaysian Ringgit" },
  { value: "SGD", label: "SGD — Singapore Dollar" },
  { value: "USD", label: "USD — US Dollar" },
  { value: "EUR", label: "EUR — Euro" },
  { value: "GBP", label: "GBP — British Pound" },
  { value: "JPY", label: "JPY — Japanese Yen" },
  { value: "CNY", label: "CNY — Chinese Yuan" },
  { value: "HKD", label: "HKD — Hong Kong Dollar" },
  { value: "KRW", label: "KRW — South Korean Won" },
  { value: "THB", label: "THB — Thai Baht" },
  { value: "IDR", label: "IDR — Indonesian Rupiah" },
  { value: "INR", label: "INR — Indian Rupee" },
  { value: "PHP", label: "PHP — Philippine Peso" },
  { value: "VND", label: "VND — Vietnamese Dong" },
  { value: "AUD", label: "AUD — Australian Dollar" },
  { value: "NZD", label: "NZD — New Zealand Dollar" },
  { value: "CAD", label: "CAD — Canadian Dollar" },
  { value: "CHF", label: "CHF — Swiss Franc" },
  { value: "AED", label: "AED — UAE Dirham" },
  { value: "SAR", label: "SAR — Saudi Riyal" },
  { value: "QAR", label: "QAR — Qatari Riyal" },
  { value: "TRY", label: "TRY — Turkish Lira" },
  { value: "ZAR", label: "ZAR — South African Rand" },
  { value: "BRL", label: "BRL — Brazilian Real" },
  { value: "MXN", label: "MXN — Mexican Peso" },
  { value: "SEK", label: "SEK — Swedish Krona" },
  { value: "NOK", label: "NOK — Norwegian Krone" },
  { value: "DKK", label: "DKK — Danish Krone" },
  { value: "PLN", label: "PLN — Polish Zloty" },
  { value: "CZK", label: "CZK — Czech Koruna" },
];
