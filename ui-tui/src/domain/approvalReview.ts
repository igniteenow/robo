import { buildToolTrailLine } from '../lib/text.js'

// The smart-approval reviewer's decision on a flagged action
// (tools/approval.py, `approval.reviewed`). Shown in the tool shelf like a
// tool call, so the person sees every review — above all the approvals it
// makes without asking anyone.
export type ApprovalReviewVerdict = 'approve' | 'deny' | 'escalate'

export interface ApprovalReview {
  command: string
  description: string
  verdict: ApprovalReviewVerdict
}

const VERDICTS: readonly ApprovalReviewVerdict[] = ['approve', 'deny', 'escalate']

const text = (value: unknown) => (typeof value === 'string' ? value.trim() : '')

export const parseApprovalReview = (payload: unknown): ApprovalReview | null => {
  const raw = (payload ?? {}) as Record<string, unknown>
  const verdict = VERDICTS.find(v => v === raw.verdict)

  return verdict ? { command: text(raw.command), description: text(raw.description), verdict } : null
}

// "auto-approved" names what actually happened: nobody was asked. The other
// two always end in the approval prompt, whose card carries the reviewer's
// reason — the line only has to say a person decides.
const NOTE: Record<ApprovalReviewVerdict, string> = {
  approve: 'auto-approved',
  deny: 'judged dangerous, asking you',
  escalate: 'not sure, asking you'
}

export const approvalReviewTrailLine = ({ command, description, verdict }: ApprovalReview) =>
  buildToolTrailLine(
    'AI_reviewer',
    command,
    verdict === 'deny',
    description ? `${NOTE[verdict]}: ${description}` : NOTE[verdict]
  )
