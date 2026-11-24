import { Handlers, PageProps } from "$fresh/server.ts";
import Layout from "../../components/Layout.tsx";
import { AuthState } from "../_middleware.ts";

interface ElectionRequest {
  id: string;
  name: string;
  type: string;
  area_description: string;
  election_date: string;
  requested_by_politician_id: string | null;
  requested_by_email: string | null;
  evidence_url: string | null;
  notes: string | null;
  status: string;
  rejection_reason: string | null;
  approved_election_id: string | null;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
}

interface PageData {
  request: ElectionRequest | null;
  error?: string;
  success?: string;
}

const typeLabels: Record<string, string> = {
  HR: "衆議院選挙",
  HC: "参議院選挙",
  PG: "知事選挙",
  CM: "市長選挙",
  GM: "議会選挙",
};

export const handler: Handlers<PageData, AuthState> = {
  async GET(_req, ctx) {
    const { id } = ctx.params;
    const apiBase = Deno.env.get("API_BASE_URL") || "http://localhost:3722";
    const apiKey = Deno.env.get("API_KEY_DEV") || Deno.env.get("API_KEY_PROD") || "dev-api-key";

    try {
      const res = await fetch(`${apiBase}/api/v1/election-requests/${id}`, {
        headers: { "X-API-Key": apiKey },
      });
      const data = await res.json();

      if (!res.ok) {
        return ctx.render({ request: null, error: data.error });
      }

      return ctx.render({ request: data.data });
    } catch (error) {
      return ctx.render({
        request: null,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    }
  },

  async POST(req, ctx) {
    const { id } = ctx.params;
    const form = await req.formData();
    const action = form.get("action");

    const apiBase = Deno.env.get("API_BASE_URL") || "http://localhost:3722";
    const authHeader = { Authorization: `Bearer ${ctx.state.accessToken}` };
    const apiKey = Deno.env.get("API_KEY_DEV") || Deno.env.get("API_KEY_PROD") || "dev-api-key";

    try {
      if (action === "approve") {
        const areaCode = form.get("area_code");
        if (!areaCode) {
          const res = await fetch(`${apiBase}/api/v1/election-requests/${id}`, {
            headers: { "X-API-Key": apiKey },
          });
          const data = await res.json();
          return ctx.render({ request: data.data, error: "選挙区コードを入力してください" });
        }

        const res = await fetch(`${apiBase}/api/admin/election-requests/${id}/approve`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            ...authHeader,
          },
          body: JSON.stringify({
            area_code: areaCode,
            reviewed_by: ctx.state.user?.name || ctx.state.user?.email || "admin",
          }),
        });

        if (!res.ok) {
          const data = await res.json();
          const reqRes = await fetch(`${apiBase}/api/v1/election-requests/${id}`, {
            headers: { "X-API-Key": apiKey },
          });
          const reqData = await reqRes.json();
          return ctx.render({ request: reqData.data, error: data.error });
        }

        return new Response(null, {
          status: 303,
          headers: { Location: "/election-requests?status=pending" },
        });
      }

      if (action === "reject") {
        const reason = form.get("rejection_reason");
        if (!reason) {
          const res = await fetch(`${apiBase}/api/v1/election-requests/${id}`, {
            headers: { "X-API-Key": apiKey },
          });
          const data = await res.json();
          return ctx.render({ request: data.data, error: "却下理由を入力してください" });
        }

        const res = await fetch(`${apiBase}/api/admin/election-requests/${id}/reject`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            ...authHeader,
          },
          body: JSON.stringify({
            rejection_reason: reason,
            reviewed_by: ctx.state.user?.name || ctx.state.user?.email || "admin",
          }),
        });

        if (!res.ok) {
          const data = await res.json();
          const reqRes = await fetch(`${apiBase}/api/v1/election-requests/${id}`, {
            headers: { "X-API-Key": apiKey },
          });
          const reqData = await reqRes.json();
          return ctx.render({ request: reqData.data, error: data.error });
        }

        return new Response(null, {
          status: 303,
          headers: { Location: "/election-requests?status=pending" },
        });
      }

      return ctx.render({ request: null, error: "Unknown action" });
    } catch (error) {
      return ctx.render({
        request: null,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    }
  },
};

export default function ElectionRequestDetail({ data }: PageProps<PageData>) {
  const { request, error, success } = data;

  if (!request) {
    return (
      <Layout active="/election-requests">
        <div class="alert alert-error">
          <span>⚠️ {error || "リクエストが見つかりません"}</span>
        </div>
        <a href="/election-requests" class="btn btn-ghost mt-4">← 戻る</a>
      </Layout>
    );
  }

  return (
    <Layout active="/election-requests">
      <div class="space-y-6">
        <div class="flex items-center gap-4">
          <a href="/election-requests" class="btn btn-ghost btn-sm">← 戻る</a>
          <h1 class="text-3xl font-bold">選挙リクエスト詳細</h1>
        </div>

        {error && (
          <div class="alert alert-error">
            <span>⚠️ {error}</span>
          </div>
        )}

        {success && (
          <div class="alert alert-success">
            <span>✅ {success}</span>
          </div>
        )}

        <div class="card bg-base-100 shadow">
          <div class="card-body">
            <h2 class="card-title text-2xl">{request.name}</h2>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div>
                <p class="text-sm opacity-70">選挙タイプ</p>
                <p class="font-medium">{typeLabels[request.type] || request.type} ({request.type})</p>
              </div>
              <div>
                <p class="text-sm opacity-70">選挙区（申請者入力）</p>
                <p class="font-medium">{request.area_description}</p>
              </div>
              <div>
                <p class="text-sm opacity-70">選挙日</p>
                <p class="font-medium">{new Date(request.election_date).toLocaleDateString("ja-JP")}</p>
              </div>
              <div>
                <p class="text-sm opacity-70">申請日</p>
                <p class="font-medium">{new Date(request.created_at).toLocaleDateString("ja-JP")}</p>
              </div>
            </div>

            {request.evidence_url && (
              <div class="mt-4">
                <p class="text-sm opacity-70">証明 URL</p>
                <a href={request.evidence_url} target="_blank" rel="noopener" class="link link-primary">
                  {request.evidence_url}
                </a>
              </div>
            )}

            {request.notes && (
              <div class="mt-4">
                <p class="text-sm opacity-70">補足情報</p>
                <p class="bg-base-200 p-3 rounded">{request.notes}</p>
              </div>
            )}
          </div>
        </div>

        {request.status === "pending" && (
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Approve Form */}
            <div class="card bg-success/10 border-2 border-success">
              <div class="card-body">
                <h3 class="card-title text-success">✅ 承認</h3>
                <form method="POST">
                  <input type="hidden" name="action" value="approve" />
                  <div class="form-control">
                    <label class="label">
                      <span class="label-text">選挙区コード（必須）</span>
                    </label>
                    <input
                      type="text"
                      name="area_code"
                      placeholder="例: 13-01"
                      class="input input-bordered"
                      required
                    />
                    <label class="label">
                      <span class="label-text-alt">形式: 都道府県コード(2桁)-選挙区番号(2桁)</span>
                    </label>
                  </div>
                  <div class="card-actions justify-end mt-4">
                    <button type="submit" class="btn btn-success">承認する</button>
                  </div>
                </form>
              </div>
            </div>

            {/* Reject Form */}
            <div class="card bg-error/10 border-2 border-error">
              <div class="card-body">
                <h3 class="card-title text-error">❌ 却下</h3>
                <form method="POST">
                  <input type="hidden" name="action" value="reject" />
                  <div class="form-control">
                    <label class="label">
                      <span class="label-text">却下理由（必須）</span>
                    </label>
                    <textarea
                      name="rejection_reason"
                      placeholder="却下の理由を入力してください"
                      class="textarea textarea-bordered"
                      rows={3}
                      required
                    ></textarea>
                  </div>
                  <div class="card-actions justify-end mt-4">
                    <button type="submit" class="btn btn-error">却下する</button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        )}

        {request.status === "approved" && (
          <div class="alert alert-success">
            <span>✅ このリクエストは承認済みです。作成された選挙ID: <code>{request.approved_election_id}</code></span>
          </div>
        )}

        {request.status === "rejected" && (
          <div class="alert alert-error">
            <span>❌ このリクエストは却下されました。理由: {request.rejection_reason}</span>
          </div>
        )}
      </div>
    </Layout>
  );
}

