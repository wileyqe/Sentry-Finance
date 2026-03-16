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

const getDomain = (name: string): string => {
  if (!name) return 'unknown.com';
  
  const cleanName = name.toLowerCase().replace(/[^a-z0-9\s.-]/g, '').trim();
  
  // 1. Check direct matches
  if (COMMON_DOMAINS[cleanName]) {
    return COMMON_DOMAINS[cleanName];
  }

  // 2. Check partial matches for tricky ones
  const parts = cleanName.split(' ');
  if (parts.length > 0) {
    const firstWord = parts[0];
    if (COMMON_DOMAINS[firstWord]) {
      return COMMON_DOMAINS[firstWord];
    }
  }

  // 3. Fallback: just strip spaces and append .com
  const guessedDomain = cleanName.replace(/\s+/g, '') + '.com';
  return guessedDomain;
};

export function TransactionLogo({ merchantName, className = '', size = 'md' }: TransactionLogoProps) {
  const [tier, setTier] = useState<0 | 1 | 2>(0);
  const [hasError, setHasError] = useState(false);

  // Reset state when merchant changes
  useEffect(() => {
    setTier(0);
    setHasError(false);
  }, [merchantName]);

  const domain = getDomain(merchantName);
  
  const sizeClasses = {
    sm: 'w-6 h-6',
    md: 'w-10 h-10',
    lg: 'w-12 h-12'
  };

  const getImageUrl = () => {
    // Tier 0: Clearbit High-Res
    if (tier === 0) {
      return `https://logo.clearbit.com/${domain}?size=128`;
    }
    // Tier 1: Google Favicon
    if (tier === 1) {
      return `https://www.google.com/s2/favicons?domain=${domain}&sz=128`;
    }
    // Tier 2: UI Avatars Fallback
    const encodedName = encodeURIComponent(merchantName || '?');
    return `https://ui-avatars.com/api/?name=${encodedName}&background=random&color=fff&size=128&bold=true`;
  };

  const handleError = () => {
    if (tier < 2) {
      setTier((prev) => (prev + 1) as 0 | 1 | 2);
    } else {
      setHasError(true);
    }
  };

  const baseClasses = `shrink-0 rounded-full border border-slate-200 dark:border-slate-700/50 bg-white dark:bg-slate-800 flex items-center justify-center overflow-hidden shadow-sm transition-transform hover:scale-105 ${sizeClasses[size]} ${className}`;

  if (hasError || !merchantName) {
    // Extreme fallback (should rarely happen due to ui-avatars)
    return (
      <div className={baseClasses}>
        <div className="w-full h-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
          <span className="material-symbols-outlined text-slate-400 text-[18px]">
            receipt_long
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className={baseClasses}>
      <img 
        src={getImageUrl()} 
        alt={`${merchantName} logo`}
        className="w-full h-full object-contain object-scale-down"
        // Some favicons are small, using scale-down ensures they don't pixelate or stretch over boundaries
        style={{ padding: tier === 1 ? '4px' : '0' }} // add a little padding to Google favicons so they don't hit the edge
        onError={handleError}
      />
    </div>
  );
}
