import { Handlers, PageProps } from "$fresh/server.ts";
import Layout from "../../components/Layout.tsx";
import { AuthState } from "../_middleware.ts";

interface OrganizationRequest {
  id: string;
  name: string;
  type: string;
  registration_authority: string | null;
  requested_by_politician_id: string | null;
  requested_by_email: string | null;
  evidence_type: string;
  evidence_file_url: string;
  evidence_file_name: string | null;
  notes: string | null;
  status: string;
  rejection_reason: string | null;
  approved_organization_id: string | null;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
}

interface PageData {
  request: OrganizationRequest | null;
  error?: string;
}

const typeLabels: Record<string, string> = {
  political_party: "政党",
  support_group: "後援会",
  fund_management: "資金管理団体",
  other: "その他",
};

const evidenceTypeLabels: Record<string, string> = {
  registration_form: "政治団体設立届出書（控え）",
  name_list: "政治団体名簿のスクリーンショット",
  financial_report: "政治資金収支報告書の表紙",
};

export const handler: Handlers<PageData, AuthState> = {
  async GET(_req, ctx) {
    const { id } = ctx.params;
    const apiBase = Deno.env.get("API_BASE_URL") || "http://localhost:3722";
    const apiKey = Deno.env.get("API_KEY_DEV") || Deno.env.get("API_KEY_PROD") || "dev-api-key";

    try {
      const res = await fetch(`${apiBase}/api/v1/organization-requests/${id}`, {
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
        const res = await fetch(`${apiBase}/api/admin/organization-requests/${id}/approve`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            ...authHeader,
          },
          body: JSON.stringify({
            reviewed_by: ctx.state.user?.name || ctx.state.user?.email || "admin",
          }),
        });

        if (!res.ok) {
          const data = await res.json();
          const reqRes = await fetch(`${apiBase}/api/v1/organization-requests/${id}`, {
            headers: { "X-API-Key": apiKey },
          });
          const reqData = await reqRes.json();
          return ctx.render({ request: reqData.data, error: data.error });
        }

        return new Response(null, {
          status: 303,
          headers: { Location: "/organization-requests?status=pending" },
        });
      }

      if (action === "reject") {
        const reason = form.get("rejection_reason");
        if (!reason) {
          const res = await fetch(`${apiBase}/api/v1/organization-requests/${id}`, {
            headers: { "X-API-Key": apiKey },
          });
          const data = await res.json();
          return ctx.render({ request: data.data, error: "却下理由を入力してください" });
        }

        const res = await fetch(`${apiBase}/api/admin/organization-requests/${id}/reject`, {
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
          const reqRes = await fetch(`${apiBase}/api/v1/organization-requests/${id}`, {
            headers: { "X-API-Key": apiKey },
          });
          const reqData = await reqRes.json();
          return ctx.render({ request: reqData.data, error: data.error });
        }

        return new Response(null, {
          status: 303,
          headers: { Location: "/organization-requests?status=pending" },
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

export default function OrganizationRequestDetail({ data }: PageProps<PageData>) {
  const { request, error } = data;

  if (!request) {
    return (
      <Layout active="/organization-requests">
        <div class="alert alert-error">
          <span>⚠️ {error || "リクエストが見つかりません"}</span>
        </div>
        <a href="/organization-requests" class="btn btn-ghost mt-4">← 戻る</a>
      </Layout>
    );
  }

  return (
    <Layout active="/organization-requests">
      <div class="space-y-6">
        <div class="flex items-center gap-4">
          <a href="/organization-requests" class="btn btn-ghost btn-sm">← 戻る</a>
          <h1 class="text-3xl font-bold">政治団体リクエスト詳細</h1>
        </div>

        {error && (
          <div class="alert alert-error">
            <span>⚠️ {error}</span>
          </div>
        )}

        <div class="card bg-base-100 shadow">
          <div class="card-body">
            <h2 class="card-title text-2xl">{request.name}</h2>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div>
                <p class="text-sm opacity-70">団体タイプ</p>
                <p class="font-medium">{typeLabels[request.type] || request.type}</p>
              </div>
              <div>
                <p class="text-sm opacity-70">届出先</p>
                <p class="font-medium">{request.registration_authority || "未指定"}</p>
              </div>
              <div>
                <p class="text-sm opacity-70">申請日</p>
                <p class="font-medium">{new Date(request.created_at).toLocaleDateString("ja-JP")}</p>
              </div>
              <div>
                <p class="text-sm opacity-70">証明書類タイプ</p>
                <p class="font-medium">{evidenceTypeLabels[request.evidence_type] || request.evidence_type}</p>
              </div>
            </div>

            <div class="mt-4">
              <p class="text-sm opacity-70">証明書類</p>
              <div class="mt-2 p-4 border-2 border-dashed border-base-300 rounded-lg">
                <a
                  href={request.evidence_file_url}
                  target="_blank"
                  rel="noopener"
                  class="btn btn-outline btn-primary"
                >
                  📎 {request.evidence_file_name || "ファイルを確認"}
                </a>
                <p class="text-sm mt-2 opacity-70">
                  クリックして証明書類を確認してください
                </p>
              </div>
            </div>

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
                <p class="text-sm opacity-70">
                  証明書類を確認し、問題なければ承認してください。
                </p>
                <form method="POST">
                  <input type="hidden" name="action" value="approve" />
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
            <span>✅ このリクエストは承認済みです。作成された団体ID: <code>{request.approved_organization_id}</code></span>
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

