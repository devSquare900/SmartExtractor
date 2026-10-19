/**
 * Utility functions for parsing and managing Interactive Document Artifacts (Canvas)
 */

export function parseArtifact(rawText) {
  if (!rawText || typeof rawText !== 'string') {
    return { hasArtifact: false, isComplete: false, artifact: null, chatText: rawText || '' };
  }

  // Regex to match <artifact ...>
  const tagStartRegex = /<artifact\s+([^>]*?)>/i;
  const startMatch = rawText.match(tagStartRegex);

  if (!startMatch) {
    return { hasArtifact: false, isComplete: false, artifact: null, chatText: rawText };
  }

  const attrString = startMatch[1] || '';
  const startIndex = startMatch.index;
  const tagLength = startMatch[0].length;
  const afterStart = rawText.slice(startIndex + tagLength);

  const endTagIndex = afterStart.indexOf('</artifact>');
  let content = '';
  let isComplete = false;
  let remainingChat = '';

  if (endTagIndex !== -1) {
    content = afterStart.slice(0, endTagIndex).trim();
    isComplete = true;
    const beforeTag = rawText.slice(0, startIndex).trim();
    const afterTag = afterStart.slice(endTagIndex + '</artifact>'.length).trim();
    remainingChat = [beforeTag, afterTag].filter(Boolean).join('\n\n');
  } else {
    // Streaming partial artifact
    content = afterStart;
    remainingChat = rawText.slice(0, startIndex).trim();
  }

  const parseAttr = (name, def = '') => {
    const m = attrString.match(new RegExp(`${name}=["']([^"']+)["']`, 'i'));
    return m ? m[1] : def;
  };

  const id = parseAttr('id', `art-${Date.now()}`);
  const title = parseAttr('title', 'Generated Document');
  const type = parseAttr('type', 'report');
  const theme = parseAttr('theme', 'navy').toLowerCase();

  return {
    hasArtifact: true,
    isComplete,
    artifact: {
      id,
      title,
      type,
      theme: ['navy', 'emerald', 'blue', 'burgundy'].includes(theme) ? theme : 'navy',
      content,
      rawTag: startMatch[0],
    },
    chatText: remainingChat
  };
}

export const THEMES = {
  navy: {
    id: 'navy',
    name: 'Executive Navy',
    accent: '#0f172a',
    accentBg: '#f8fafc',
    border: '#cbd5e1',
    headerBg: '#0f172a',
    headerText: '#ffffff',
    highlight: '#2563eb'
  },
  emerald: {
    id: 'emerald',
    name: 'Corporate Emerald',
    accent: '#065f46',
    accentBg: '#f0fdf4',
    border: '#a7f3d0',
    headerBg: '#065f46',
    headerText: '#ffffff',
    highlight: '#059669'
  },
  blue: {
    id: 'blue',
    name: 'Royal Blue',
    accent: '#1e40af',
    accentBg: '#eff6ff',
    border: '#bfdbfe',
    headerBg: '#1e40af',
    headerText: '#ffffff',
    highlight: '#3b82f6'
  },
  burgundy: {
    id: 'burgundy',
    name: 'Classic Crimson',
    accent: '#881337',
    accentBg: '#fff1f2',
    border: '#fecdd3',
    headerBg: '#881337',
    headerText: '#ffffff',
    highlight: '#e11d48'
  }
};
