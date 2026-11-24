import { Handlers, PageProps } from "$fresh/server.ts";

/**
 * パスワード設定ページ
 *
 * 招待メールのリンクからリダイレクトされた後、
 * 新しいパスワードを設定する。
 */

interface SetPasswordData {
  accessToken: string;
  refreshToken: string;
  error?: string;
  success?: boolean;
}

export const handler: Handlers<SetPasswordData> = {
  GET(req, ctx) {
    const url = new URL(req.url);
    const accessToken = url.searchParams.get("access_token") || "";
    const refreshToken = url.searchParams.get("refresh_token") || "";

    if (!accessToken || !refreshToken) {
      return new Response(null, {
        status: 302,
        headers: { Location: "/login?error=invalid_link" },
      });
    }

    return ctx.render({ accessToken, refreshToken });
  },

  async POST(req, ctx) {
    const form = await req.formData();
    const accessToken = form.get("access_token")?.toString() || "";
    const refreshToken = form.get("refresh_token")?.toString() || "";
    const password = form.get("password")?.toString() || "";
    const confirmPassword = form.get("confirm_password")?.toString() || "";

    if (!password || !confirmPassword) {
      return ctx.render({
        accessToken,
        refreshToken,
        error: "パスワードを入力してください",
      });
    }

    if (password !== confirmPassword) {
      return ctx.render({
        accessToken,
        refreshToken,
        error: "パスワードが一致しません",
      });
    }

    if (password.length < 8) {
      return ctx.render({
        accessToken,
        refreshToken,
        error: "パスワードは8文字以上で設定してください",
      });
    }

    // Supabase API でパスワードを更新
    const apiBase = Deno.env.get("API_BASE_URL") || "http://localhost:3722";
    try {
      const res = await fetch(`${apiBase}/api/auth/update-password`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ password }),
      });

      if (!res.ok) {
        const json = await res.json();
        return ctx.render({
          accessToken,
          refreshToken,
          error: json.error || "パスワードの更新に失敗しました",
        });
      }

      // 成功 - ログインページへリダイレクト
      return new Response(null, {
        status: 302,
        headers: { Location: "/login?message=password_set" },
      });
    } catch (e) {
      console.error("Password update error:", e);
      return ctx.render({
        accessToken,
        refreshToken,
        error: "ネットワークエラーが発生しました",
      });
    }
  },
};

export default function SetPasswordPage({ data }: PageProps<SetPasswordData>) {
  return (
    <div class="min-h-screen flex items-center justify-center bg-base-200">
      <div class="card w-full max-w-md bg-base-100 shadow-xl">
        <div class="card-body">
          <div class="text-center mb-6">
            <h1 class="text-2xl font-bold">🔑 パスワード設定</h1>
            <p class="text-sm opacity-70 mt-2">
              新しいパスワードを設定してください
            </p>
          </div>

          {data.error && (
            <div class="alert alert-error mb-4">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                class="stroke-current shrink-0 h-6 w-6"
                fill="none"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              <span>{data.error}</span>
            </div>
          )}

          <form method="POST">
            <input type="hidden" name="access_token" value={data.accessToken} />
            <input type="hidden" name="refresh_token" value={data.refreshToken} />

            <div class="form-control">
              <label class="label">
                <span class="label-text">新しいパスワード</span>
              </label>
              <input
                type="password"
                name="password"
                placeholder="8文字以上"
                class="input input-bordered"
                required
                minLength={8}
                autocomplete="new-password"
              />
            </div>

            <div class="form-control mt-4">
              <label class="label">
                <span class="label-text">パスワード確認</span>
              </label>
              <input
                type="password"
                name="confirm_password"
                placeholder="もう一度入力"
                class="input input-bordered"
                required
                minLength={8}
                autocomplete="new-password"
              />
            </div>

            <div class="form-control mt-6">
              <button type="submit" class="btn btn-primary">
                パスワードを設定
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
