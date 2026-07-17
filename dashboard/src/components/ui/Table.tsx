import { ReactNode } from 'react';

interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  className?: string;
  headerClassName?: string;
}

interface TableProps<T> {
  data: T[];
  columns: Column<T>[];
  keyExtractor: (row: T) => string;
  className?: string;
  emptyMessage?: string;
  striped?: boolean;
  hoverable?: boolean;
  onRowClick?: (row: T) => void;
}

export function Table<T>({ 
  data, 
  columns, 
  keyExtractor, 
  className = '', 
  emptyMessage = 'No data available',
  striped = true,
  hoverable = true,
  onRowClick 
}: TableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="text-center py-12 text-text-secondary">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className={`overflow-x-auto rounded-lg border border-border-color ${className}`}>
      <table className="w-full text-sm">
        <thead className="bg-bg-tertiary">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-3 text-left font-medium text-text-secondary uppercase tracking-wider ${col.headerClassName || ''}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border-color">
          {data.map((row) => (
            <tr
              key={keyExtractor(row)}
              className={`${striped ? 'odd:bg-bg-tertiary/50' : ''} ${hoverable ? 'hover:bg-bg-tertiary/50' : ''} ${onRowClick ? 'cursor-pointer' : ''} transition-colors`}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`px-4 py-3 text-text-primary ${col.className || ''}`}
                >
                  {col.render ? col.render(row) : (row as any)[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
