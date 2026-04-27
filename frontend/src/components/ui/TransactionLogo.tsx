import { useState, useEffect } from 'react';

interface TransactionLogoProps {
  merchantName: string;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}

const COMMON_DOMAINS: Record<string, string> = {
  'amazon': 'amazon.com',
  'amzn': 'amazon.com',
  'amzn.com/bill': 'amazon.com',
  'target': 'target.com',
  'walmart': 'walmart.com',
  'starbucks': 'starbucks.com',
  'uber': 'uber.com',
  'uber eats': 'ubereats.com',
  'doordash': 'doordash.com',
  'lyft': 'lyft.com',
  'netflix': 'netflix.com',
  'spotify': 'spotify.com',
  'hulu': 'hulu.com',
  'apple': 'apple.com',
  'apple.com/bill': 'apple.com',
  'google': 'google.com',
  'microsoft': 'microsoft.com',
  'chase': 'chase.com',
  'bank of america': 'bankofamerica.com',
  'bofa': 'bankofamerica.com',
  'wells fargo': 'wellsfargo.com',
  'capital one': 'capitalone.com',
  'citi': 'citi.com',
  'discover': 'discover.com',
  'american express': 'americanexpress.com',
  'amex': 'americanexpress.com',
  'fidelity': 'fidelity.com',
  'charles schwab': 'schwab.com',
  'vanguard': 'vanguard.com',
  'acorns': 'acorns.com',
  'robinhood': 'robinhood.com',
  'coinbase': 'coinbase.com',
  'paypal': 'paypal.com',
  'venmo': 'venmo.com',
  'cash app': 'cash.app',
  'zelle': 'zellepay.com',
  'mcdonalds': 'mcdonalds.com',
  'chick-fil-a': 'chick-fil-a.com',
  'chipotle': 'chipotle.com',
  'home depot': 'homedepot.com',
  'lowes': 'lowes.com',
  'best buy': 'bestbuy.com',
  'costco': 'costco.com',
  'whole foods': 'wholefoodsmarket.com',
  'trader joes': 'traderjoes.com',
  'kroger': 'kroger.com',
  'safeway': 'safeway.com',
  'cvs': 'cvs.com',
  'walgreens': 'walgreens.com',
  'shell': 'shell.us',
  'chevron': 'chevron.com',
  'exxon': 'exxon.com',
  'mobil': 'exxon.com',
  'arco': 'arco.com',
  'pg&e': 'pge.com',
  'at&t': 'att.com',
  'verizon': 'verizon.com',
  't-mobile': 't-mobile.com',
  'comcast': 'xfinity.com',
  'xfinity': 'xfinity.com',
  'spectrum': 'spectrum.com',
};

const getDomain = (name: string): string | null => {
  if (!name) return null;
  
  const cleanName = name.toLowerCase().replace(/[^a-z0-9\s&.'/-]/g, '').trim();
  
  // 1. Check direct matches
  if (COMMON_DOMAINS[cleanName]) {
    return COMMON_DOMAINS[cleanName];
  }

  // 2. Check partial matches — try first word, then first two words
  const parts = cleanName.split(/\s+/);
  if (parts.length > 0) {
    const firstWord = parts[0];
    if (COMMON_DOMAINS[firstWord]) {
      return COMMON_DOMAINS[firstWord];
    }
    if (parts.length > 1) {
      const twoWords = parts.slice(0, 2).join(' ');
      if (COMMON_DOMAINS[twoWords]) {
        return COMMON_DOMAINS[twoWords];
      }
    }
  }

  // 3. Check if any key is a substring of the merchant name (e.g., "amazon marketplace" matches "amazon")
  for (const [key, domain] of Object.entries(COMMON_DOMAINS)) {
    if (cleanName.includes(key)) {
      return domain;
    }
  }

  // No match — return null to skip network request
  return null;
};

// Generate a consistent color from a string (for letter avatar).
// 20 colors at lightness 0.55, chroma 0.13, stepped around the Ember hue
// wheel so avatars stay distinct but harmonize with the warm palette.
const getAvatarColor = (name: string): string => {
  const colors = [
    'oklch(0.55 0.13 40)',    // terracotta (c1 echo)
    'oklch(0.55 0.13 60)',    // orange
    'oklch(0.55 0.13 80)',    // amber (c3 echo)
    'oklch(0.55 0.13 100)',   // yellow-olive
    'oklch(0.55 0.13 120)',   // olive (c5 echo)
    'oklch(0.55 0.13 145)',   // gain-green
    'oklch(0.55 0.13 170)',   // teal-green
    'oklch(0.55 0.13 200)',   // teal (c2 echo)
    'oklch(0.55 0.13 220)',   // blue-teal
    'oklch(0.55 0.13 240)',   // slate-blue
    'oklch(0.55 0.13 260)',   // cobalt
    'oklch(0.55 0.13 280)',   // indigo
    'oklch(0.55 0.13 300)',   // purple
    'oklch(0.55 0.13 320)',   // magenta
    'oklch(0.55 0.13 340)',   // plum (c4 echo)
    'oklch(0.55 0.13 355)',   // pink-rose
    'oklch(0.55 0.13 15)',    // burgundy (c6 echo)
    'oklch(0.55 0.13 25)',    // red-orange
    'oklch(0.48 0.12 50)',    // burnt sienna (primary-hover echo)
    'oklch(0.62 0.12 85)',    // gold (c8 echo)
  ];
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return colors[Math.abs(hash) % colors.length];
};

export function TransactionLogo({ merchantName, className = '', size = 'md' }: TransactionLogoProps) {
  const domain = getDomain(merchantName);
  const [tier, setTier] = useState<0 | 1 | 2>(domain ? 0 : 2);
  const [hasError, setHasError] = useState(false);

  // Reset state when merchant changes
  useEffect(() => {
    const newDomain = getDomain(merchantName);
    setTier(newDomain ? 0 : 2);
    setHasError(false);
  }, [merchantName]);

  const sizeClasses = {
    sm: 'w-6 h-6',
    md: 'w-10 h-10',
    lg: 'w-12 h-12'
  };

  const fontSizeClasses = {
    sm: 'text-xs',
    md: 'text-base',
    lg: 'text-lg'
  };

  const getImageUrl = () => {
    if (!domain) return null;
    // Tier 0: Clearbit High-Res
    if (tier === 0) {
      return `https://logo.clearbit.com/${domain}?size=128`;
    }
    // Tier 1: Google Favicon
    if (tier === 1) {
      return `https://www.google.com/s2/favicons?domain=${domain}&sz=128`;
    }
    return null;
  };

  const handleError = () => {
    if (tier < 1) {
      setTier((prev) => (prev + 1) as 0 | 1 | 2);
    } else {
      setTier(2);
      setHasError(true);
    }
  };

  const baseClasses = `shrink-0 rounded-full border border-border bg-card flex items-center justify-center overflow-hidden shadow-sm transition-transform hover:scale-105 ${sizeClasses[size]} ${className}`;

  // Letter avatar: default path for unknown merchants, or fallback for failed lookups
  const firstChar = (merchantName || '?').charAt(0).toUpperCase();
  const avatarColor = getAvatarColor(merchantName || '?');

  const imageUrl = getImageUrl();
  if (!imageUrl || tier >= 2 || hasError || !merchantName) {
    return (
      <div className={baseClasses}>
        <div
          className="w-full h-full flex items-center justify-center"
          style={{ backgroundColor: avatarColor }}
        >
          <span className={`font-bold text-white ${fontSizeClasses[size]}`}>
            {firstChar}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className={baseClasses}>
      <img 
        src={imageUrl} 
        alt={`${merchantName} logo`}
        className="w-full h-full object-contain object-scale-down"
        style={{ padding: tier === 1 ? '4px' : '0' }}
        onError={handleError}
      />
    </div>
  );
}
