import type { Metadata } from "next";

import { Providers } from "./providers";
import "./styles.css";

export const metadata: Metadata = {
  title: "EMG Studio",
  description: "Secure knowledge exploration for the EMG Platform",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
