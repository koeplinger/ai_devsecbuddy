import type { ReactNode } from 'react';
import type { Finding } from '../types';

// A presentation-ready executive summary built from the *actual* probe data on the finding,
// so it can be read aloud or pasted onto a slide. Four knock-out sections: What happened /
// How I probed it / Example / Why this is bad.

const num = (v: unknown): number | undefined => (typeof v === 'number' ? v : undefined);
const clip = (s: string, n = 420): string => (s.length > n ? s.slice(0, n).trimEnd() + '…' : s);

// The adversarial payload is "<clean resume>\n\n<injection>"; the injected instruction is
// the trailing blank-line-separated block.
function injectionTail(payload: unknown): string {
  if (typeof payload !== 'string') return '';
  const blocks = payload.split(/\n[ \t]*\n/);
  return (blocks[blocks.length - 1] || '').trim();
}

interface Sections {
  whatHappened: string;
  howProbed: string;
  example: ReactNode;
  whyBad: string;
}

function build(finding: Finding): Sections {
  const owasp = finding.owasp_ref;
  // evidence/repro are free-form JSON captured at probe time.
  const ev = ((finding as unknown as { evidence?: Record<string, unknown> }).evidence ?? {}) as Record<string, unknown>;
  const resp = (ev.response ?? {}) as Record<string, unknown>;
  const repro = (finding.repro ?? {}) as Record<string, unknown>;
  const req = (repro.request ?? {}) as Record<string, unknown>;

  if (finding.category === 'unscorable_response') {
    const text = typeof resp.text === 'string' ? resp.text : '';
    return {
      whatHappened: `The model returned an unusable response — no score could be parsed from it — so this probe could not be evaluated for security at all.`,
      howProbed:
        finding.detail || `A standard probe was run, but the model produced no parseable score to judge.`,
      example: text ? (
        <div className="exec-example">
          <div className="exec-io">
            <span className="exec-io-label">Model returned</span>
            <code>{clip(text) || '(empty / unparseable response)'}</code>
          </div>
        </div>
      ) : (
        <p className="exec-example-plain">{finding.detail}</p>
      ),
      whyBad: `A model that can't reliably emit a parseable score can't be assessed for these attacks — this is a robustness gap, not a confirmed vulnerability. Make the model return well-formed output before drawing security conclusions.`,
    };
  }

  if (finding.category === 'prompt_injection' || finding.category === 'modal_jailbreak') {
    const jailbreak = finding.category === 'modal_jailbreak';
    const kind = jailbreak ? 'persona / "DAN" jailbreak' : 'prompt-injection';
    const score = num(resp.score);
    const delta = num(finding.metric_value);
    const baseline = score != null && delta != null ? Math.round(score - delta) : undefined;
    const inj = injectionTail(req.injected_payload);
    const respText = typeof resp.text === 'string' ? resp.text : score != null ? `score ${score}/100` : '';
    return {
      whatHappened:
        `The résumé scorer obeyed a hidden ${kind} instruction planted in an applicant's résumé` +
        (score != null ? ` and returned ${score}/100` : '') +
        (delta != null && baseline != null
          ? ` — ${delta} points above the candidate's true baseline of ${baseline}.`
          : '.'),
      howProbed: `A clean résumé was re-scored after appending the ${kind} payload, then the new score was compared against the model's learned baseline for that résumé.`,
      example: (
        <div className="exec-example">
          <div className="exec-io">
            <span className="exec-io-label">Planted in the résumé</span>
            <code>{clip(inj) || '(adversarial payload)'}</code>
          </div>
          <div className="exec-io">
            <span className="exec-io-label">Model returned</span>
            <code>{clip(respText)}</code>
          </div>
        </div>
      ),
      whyBad: `Any applicant can rig their own score by smuggling commands into résumé text — the model can't tell trusted instructions from untrusted data (OWASP ${owasp}).`,
    };
  }

  if (finding.category === 'data_exfiltration') {
    const text = typeof resp.text === 'string' ? resp.text : '';
    const leaked = text.includes('[disclosed]') ? (text.split('[disclosed]').pop() || '').trim() : text.trim();
    return {
      whatHappened: `Prompted through résumé content, the scorer disclosed its own confidential system instructions and scoring rubric back to the applicant.`,
      howProbed: `The scorer was asked — via the résumé text — to repeat its instructions, and the output was scanned for system-prompt / rubric markers.`,
      example: (
        <div className="exec-example">
          <div className="exec-io">
            <span className="exec-io-label">Model disclosed</span>
            <code>{clip(leaked) || '(leaked system prompt)'}</code>
          </div>
        </div>
      ),
      whyBad: `Leaking the rubric and system prompt lets an attacker reverse-engineer and reliably game the scorer (OWASP ${owasp}).`,
    };
  }

  if (finding.category === 'bias_fairness') {
    const mean = num(finding.metric_value);
    const variants = (Array.isArray(resp.variants) ? [...(resp.variants as Record<string, unknown>[])] : [])
      .sort((a, b) => (num(b.abs_delta) ?? 0) - (num(a.abs_delta) ?? 0));
    const top = variants.slice(0, 3);
    const ex = top[0];
    const proxy = top.some((v) => v.interest_swapped);
    return {
      whatHappened:
        (proxy
          ? `Changing the applicant's name — and swapping their listed interests to a different demographic — `
          : `Changing only the applicant's name on an otherwise identical résumé `) +
        `shifted the score by ${mean != null ? mean.toFixed(1) : '—'} points on average` +
        (ex ? ` — e.g. "${ex.a}" scored ${ex.score_a} but "${ex.b}" scored ${ex.score_b}.` : '.'),
      howProbed: `Each résumé was re-scored under counterfactual name swaps across gender and ethnicity${proxy ? ' (with a matching interest swap)' : ''}, measuring the score change attributable solely to the applicant's identity.`,
      example: (
        <div className="exec-example">
          {top.map((v, i) => {
            const sa = num(v.score_a) ?? 0;
            const sb = num(v.score_b) ?? 0;
            const d = sb - sa; // signed change from the name swap (+ favoured, − penalised)
            return (
              <div className="exec-swap" key={i}>
                <code>{String(v.a)}</code> <b>{sa}</b>
                <span className="exec-arrow">→</span>
                <code>{String(v.b)}</code> <b>{sb}</b>
                <span className="exec-delta">
                  {d < 0 ? '−' : '+'}
                  {Math.abs(d)} ({String(v.axis)})
                </span>
              </div>
            );
          })}
        </div>
      ),
      whyBad: `Identical qualifications are scored differently based on demographic signals in the name — a direct hiring-discrimination and fairness failure (OWASP ${owasp}).`,
    };
  }

  // Fallback for any other category.
  return {
    whatHappened: finding.detail,
    howProbed: `Automated adversarial probe (${finding.vector_id}) against the ${finding.tile_id} tile.`,
    example: <p className="exec-example-plain">{finding.detail}</p>,
    whyBad: `See OWASP ${owasp}.`,
  };
}

export function FindingExecSummary({ finding }: { finding: Finding }) {
  const s = build(finding);
  return (
    <section className="exec-summary" aria-label="Executive summary">
      <h4 className="exec-section">What happened</h4>
      <p>{s.whatHappened}</p>
      <h4 className="exec-section">How I probed it</h4>
      <p>{s.howProbed}</p>
      <h4 className="exec-section">Example</h4>
      {s.example}
      <h4 className="exec-section">Why this is bad</h4>
      <p>{s.whyBad}</p>
      <h4 className="exec-section">How to fix it</h4>
      <p>{finding.mitigation_guidance}</p>
    </section>
  );
}
