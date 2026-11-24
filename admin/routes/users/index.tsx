import { Handlers, PageProps } from "$fresh/server.ts";
import Layout from "../../components/Layout.tsx";
import { AuthState } from "../_middleware.ts";

interface AdminUser {
  id: string;
  email: string;
  name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface PageData {
  users: AdminUser[];
  currentUser: AuthState["user"];
  devMode: boolean;
  error?: string;
  success?: string;
}

export const handler: Handlers<PageData, AuthState> = {
  async GET(_req, ctx) {
    const apiBase = Deno.env.get("API_BASE_URL") || "http://localhost:3722";

    try {
      const res = await fetch(`${apiBase}/api/admin/users`, {
        headers: { Authorization: `Bearer ${ctx.state.accessToken}` },
      });
      const data = await res.json();

      return ctx.render({
        users: data.data || [],
        currentUser: ctx.state.user,
        devMode: ctx.state.devMode,
      });
    } catch (error) {
      return ctx.render({
        users: [],
        currentUser: ctx.state.user,
        devMode: ctx.state.devMode,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    }
  },

  async POST(req, ctx) {
    const apiBase = Deno.env.get("API_BASE_URL") || "http://localhost:3722";
    const form = await req.formData();
    const action = form.get("action")?.toString();

    try {
      if (action === "invite") {
        const email = form.get("email")?.toString();
        const name = form.get("name")?.toString();
        const role = form.get("role")?.toString() || "admin";

        if (!email) {
        return ctx.render({
          users: [],
          currentUser: ctx.state.user,
          devMode: ctx.state.devMode,
          error: "メールアドレスは必須です",
        });
        }

        const res = await fetch(`${apiBase}/api/admin/users`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${ctx.state.accessToken}`,
          },
          body: JSON.stringify({ email, name, role }),
        });

        const data = await res.json();

        if (!res.ok) {
          throw new Error(data.error || "招待に失敗しました");
        }

        // 成功後にリダイレクト
        return new Response(null, {
          status: 302,
          headers: { Location: "/users?success=invited" },
        });
      }

      if (action === "deactivate") {
        const userId = form.get("user_id")?.toString();

        if (!userId) {
          throw new Error("User ID is required");
        }

        const res = await fetch(`${apiBase}/api/admin/users/${userId}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${ctx.state.accessToken}` },
        });

        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.error || "無効化に失敗しました");
        }

        return new Response(null, {
          status: 302,
          headers: { Location: "/users?success=deactivated" },
        });
      }

      if (action === "activate") {
        const userId = form.get("user_id")?.toString();

        if (!userId) {
          throw new Error("User ID is required");
        }

        const res = await fetch(`${apiBase}/api/admin/users/${userId}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${ctx.state.accessToken}`,
          },
          body: JSON.stringify({ is_active: true }),
        });

        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.error || "有効化に失敗しました");
        }

        return new Response(null, {
          status: 302,
          headers: { Location: "/users?success=activated" },
        });
      }

      if (action === "reset_password") {
        const userId = form.get("user_id")?.toString();

        if (!userId) {
          throw new Error("User ID is required");
        }

        const res = await fetch(`${apiBase}/api/admin/users/${userId}/reset-password`, {
          method: "POST",
          headers: { Authorization: `Bearer ${ctx.state.accessToken}` },
        });

        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.error || "リセットメール送信に失敗しました");
        }

        return new Response(null, {
          status: 302,
          headers: { Location: "/users?success=reset_sent" },
        });
      }

      throw new Error("Unknown action");
    } catch (error) {
      // エラー時はユーザー一覧を再取得
      const res = await fetch(`${apiBase}/api/admin/users`, {
        headers: { Authorization: `Bearer ${ctx.state.accessToken}` },
      });
      const data = await res.json();

      return ctx.render({
        users: data.data || [],
        currentUser: ctx.state.user,
        devMode: ctx.state.devMode,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    }
  },
};

const roleLabels: Record<string, { label: string; class: string }> = {
  super_admin: { label: "スーパー管理者", class: "badge-primary" },
  admin: { label: "管理者", class: "badge-secondary" },
};

const successMessages: Record<string, string> = {
  invited: "招待メールを送信しました",
  deactivated: "ユーザーを無効化しました",
  activated: "ユーザーを有効化しました",
  reset_sent: "パスワードリセットメールを送信しました",
};

export default function UsersPage({ data, url }: PageProps<PageData>) {
  const success = url.searchParams.get("success");

  return (
    <Layout active="/users" devMode={data.devMode}>
      <div class="space-y-6">
        <div class="flex items-center justify-between">
          <h1 class="text-3xl font-bold">👥 管理者ユーザー</h1>
        </div>

        {data.error && (
          <div class="alert alert-error">
            <span>⚠️ {data.error}</span>
          </div>
        )}

        {success && successMessages[success] && (
          <div class="alert alert-success">
            <span>✅ {successMessages[success]}</span>
          </div>
        )}

        {/* 招待フォーム */}
        <div class="card bg-base-100 shadow">
          <div class="card-body">
            <h2 class="card-title">➕ 新しい管理者を招待</h2>
            <form method="POST" class="flex flex-wrap gap-4 items-end">
              <input type="hidden" name="action" value="invite" />

              <div class="form-control">
                <label class="label">
                  <span class="label-text">メールアドレス *</span>
                </label>
                <input
                  type="email"
                  name="email"
                  placeholder="admin@example.com"
                  class="input input-bordered w-64"
                  required
                />
              </div>

              <div class="form-control">
                <label class="label">
                  <span class="label-text">名前</span>
                </label>
                <input
                  type="text"
                  name="name"
                  placeholder="山田太郎"
                  class="input input-bordered w-48"
                />
              </div>

              <div class="form-control">
                <label class="label">
                  <span class="label-text">役割</span>
                </label>
                <select name="role" class="select select-bordered">
                  <option value="admin">管理者</option>
                  <option value="super_admin">スーパー管理者</option>
                </select>
              </div>

              <button type="submit" class="btn btn-primary">
                📧 招待メールを送信
              </button>
            </form>
          </div>
        </div>

        {/* ユーザー一覧 */}
        <div class="card bg-base-100 shadow">
          <div class="card-body">
            <h2 class="card-title">📋 管理者一覧</h2>

            {data.users.length === 0 ? (
              <p class="text-sm opacity-70">管理者がいません</p>
            ) : (
              <div class="overflow-x-auto">
                <table class="table">
                  <thead>
                    <tr>
                      <th>名前 / メール</th>
                      <th>役割</th>
                      <th>状態</th>
                      <th>登録日</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.users.map((user) => (
                      <tr key={user.id} class={!user.is_active ? "opacity-50" : ""}>
                        <td>
                          <div>
                            <p class="font-bold">{user.name || "(未設定)"}</p>
                            <p class="text-sm opacity-70">{user.email}</p>
                          </div>
                        </td>
                        <td>
                          <span
                            class={`badge ${
                              roleLabels[user.role]?.class || "badge-ghost"
                            }`}
                          >
                            {roleLabels[user.role]?.label || user.role}
                          </span>
                        </td>
                        <td>
                          {user.is_active ? (
                            <span class="badge badge-success">有効</span>
                          ) : (
                            <span class="badge badge-error">無効</span>
                          )}
                        </td>
                        <td class="text-sm">
                          {new Date(user.created_at).toLocaleDateString("ja-JP")}
                        </td>
                        <td>
                          {user.id !== data.currentUser?.id ? (
                            <div class="flex gap-2">
                              <form method="POST">
                                <input type="hidden" name="user_id" value={user.id} />
                                <input type="hidden" name="action" value="reset_password" />
                                <button
                                  type="submit"
                                  class="btn btn-xs btn-ghost"
                                  title="パスワードリセット"
                                >
                                  🔑
                                </button>
                              </form>

                              {user.is_active ? (
                                <form method="POST">
                                  <input type="hidden" name="user_id" value={user.id} />
                                  <input type="hidden" name="action" value="deactivate" />
                                  <button
                                    type="submit"
                                    class="btn btn-xs btn-error"
                                    title="無効化"
                                    onclick="return confirm('このユーザーを無効化しますか？')"
                                  >
                                    🚫
                                  </button>
                                </form>
                              ) : (
                                <form method="POST">
                                  <input type="hidden" name="user_id" value={user.id} />
                                  <input type="hidden" name="action" value="activate" />
                                  <button
                                    type="submit"
                                    class="btn btn-xs btn-success"
                                    title="有効化"
                                  >
                                    ✅
                                  </button>
                                </form>
                              )}
                            </div>
                          ) : (
                            <span class="text-sm opacity-50">（自分）</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
