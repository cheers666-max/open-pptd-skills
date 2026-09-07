// Explicitly loaded only by eval/review.py; never installed into global pi config.
import { realpathSync } from 'node:fs';
import { isAbsolute, relative, resolve } from 'node:path';

export function checkReadOnlyCall(event, caseRoot) {
  const deny = (reason) => ({ block: true, reason: `Independent review: ${reason}` });
  if (!caseRoot || !['read', 'grep', 'find', 'ls'].includes(event.toolName)) {
    return deny('only read/grep/find/ls within the current case are allowed');
  }
  const requested = event.input?.path ?? '.';
  if (typeof requested !== 'string' || requested.startsWith('~') || requested.startsWith('@')) {
    return deny('use an ordinary path inside this case');
  }
  try {
    const root = realpathSync(caseRoot);
    const target = realpathSync(resolve(root, requested));
    const rel = relative(root, target);
    if (rel === '..' || rel.startsWith('../') || isAbsolute(rel)) {
      return deny('path resolves outside this case');
    }
  } catch {
    return deny('path does not exist or cannot be resolved safely');
  }
}

export default function install(pi) {
  pi.on('tool_call', (event) => checkReadOnlyCall(event, process.env.PI_EVAL_REVIEW_ROOT));
}
