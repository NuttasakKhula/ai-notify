"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    ...options,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "ai-notify",
      ...options?.headers,
    },
  });
  const data = await response.json();
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : "ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบช่องกรอกข้อมูล";
    throw new ApiError(detail, response.status);
  }
  return data as T;
}

export function useResource<T>(path: string | null, revision = 0) {
  const router = useRouter();
  const [state, setState] = useState<{
    path: string;
    data?: T;
    error?: string;
  }>();
  useEffect(() => {
    if (!path) return;
    let active = true;
    const load = () =>
      api<T>(path)
        .then((data) => {
          if (active) setState({ path, data });
        })
        .catch((error: Error) => {
          if (active) {
            if (error instanceof ApiError && error.status === 401)
              router.replace("/login");
            setState({ path, error: error.message });
          }
        });
    void load();
    const interval = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [path, revision, router]);
  return state?.path === path ? state : undefined;
}

export function date(value?: string | null) {
  return value
    ? new Date(value).toLocaleString("th-TH", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";
}
