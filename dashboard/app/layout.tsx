import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { QueryProvider } from "@/lib/query-provider";
import { Toaster } from "@/components/ui/toaster";
import { AuthProvider } from "@/components/auth/AuthContext";
import { AuthGuard } from "@/components/auth/AuthGuard";
import { UserBadge } from "@/components/auth/UserBadge";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "FlowWatch - AI Workflow Observability",
  description: "Real-time observability for no-code AI workflows",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <QueryProvider>
          <AuthProvider>
            <div className="min-h-screen bg-gray-50">
              <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
                <div className="text-sm text-gray-500">
                  FlowWatch \u00b7 Sprint 1
                </div>
                <UserBadge />
              </header>
              <AuthGuard>{children}</AuthGuard>
            </div>
            <Toaster />
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}