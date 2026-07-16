import { FC } from 'react';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'neutral';
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export const Badge: FC<BadgeProps> = ({ 
  children, 
  variant = 'default', 
  size = 'md', 
  className = '' 
}) => {
  const variantStyles = {
    default: 'bg-bg-tertiary text-text-secondary',
    success: 'bg-accent-success/15 text-accent-success border-accent-success/30',
    warning: 'bg-accent-warning/15 text-accent-warning border-accent-warning/30',
    danger: 'bg-accent-danger/15 text-accent-danger border-accent-danger/30',
    info: 'bg-accent-info/15 text-accent-info border-accent-info/30',
    neutral: 'bg-bg-tertiary text-text-primary',
  };

  const sizeStyles = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-1 text-sm',
    lg: 'px-3 py-1.5 text-base',
  };

  return (
    <span 
      className={`inline-flex items-center font-medium rounded-full border ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
    >
      {children}
    </span>
  );
};
