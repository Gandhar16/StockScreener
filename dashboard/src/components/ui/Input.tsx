import { FC, InputHTMLAttributes, forwardRef } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, className = '', id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');
    
    return (
      <div className="w-full">
        {label && (
          <label htmlFor={inputId} className="block text-sm font-medium text-text-secondary mb-1.5">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={`w-full bg-bg-secondary border rounded-lg px-3 py-2 text-text-primary 
            focus:outline-none focus:ring-2 focus:ring-accent-primary focus:border-transparent
            ${error ? 'border-accent-danger' : 'border-border-color'}
            placeholder:text-text-muted
            ${className}`}
          {...props}
        />
        {error && <p className="mt-1.5 text-sm text-accent-danger">{error}</p>}
        {helperText && !error && <p className="mt-1.5 text-sm text-text-muted">{helperText}</p>}
      </div>
    );
  }
);

Input.displayName = 'Input';
