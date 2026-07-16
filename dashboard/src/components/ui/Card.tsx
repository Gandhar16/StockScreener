import { FC, ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  hover?: boolean;
  onClick?: () => void;
}

export const Card: FC<CardProps> = ({ 
  children, 
  className = '', 
  padding = 'md', 
  hover = false,
  onClick 
}) => {
  const paddingStyles = {
    none: '',
    sm: 'p-3',
    md: 'p-5',
    lg: 'p-6',
  };

  return (
    <div
      className={`bg-card border border-border-color rounded-xl ${paddingStyles[padding]} ${hover ? 'hover:border-accent-primary/50 hover:shadow-lg transition-all cursor-pointer' : ''} ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') onClick(); } : undefined}
    >
      {children}
    </div>
  );
};

export const CardHeader: FC<{ children: ReactNode; className?: string }> = ({ children, className = '' }) => (
  <div className={`mb-4 ${className}`}>{children}</div>
);

export const CardTitle: FC<{ children: ReactNode; className?: string }> = ({ children, className = '' }) => (
  <h3 className={`text-lg font-semibold text-text-primary ${className}`}>{children}</h3>
);

export const CardDescription: FC<{ children: ReactNode; className?: string }> = ({ children, className = '' }) => (
  <p className={`text-sm text-text-secondary mt-1 ${className}`}>{children}</p>
);

export const CardContent: FC<{ children: ReactNode; className?: string }> = ({ children, className = '' }) => (
  <div className={className}>{children}</div>
);

export const CardFooter: FC<{ children: ReactNode; className?: string }> = ({ children, className = '' }) => (
  <div className={`mt-4 pt-4 border-t border-border-color ${className}`}>{children}</div>
);
