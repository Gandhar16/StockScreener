import { FC, ReactNode, useState } from 'react';
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { Badge } from '../ui/Badge';

const navigation = [
  { path: '/dashboard', label: 'Dashboard', icon: '📊' },
  { path: '/calls', label: 'Equity Calls', icon: '📈' },
  { path: '/scanner', label: 'Scanner', icon: '🔍' },
  { path: '/backtest', label: 'Backtest', icon: '📜' },
  { path: '/settings', label: 'Settings', icon: '⚙️' },
];

export const Layout: FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const location = useLocation();

  return (
    <div className="flex h-screen bg-bg-primary overflow-hidden">
      {/* Sidebar */}
      <aside 
        className={`fixed inset-y-0 left-0 z-50 bg-card border-r border-border-color transition-all duration-300 ${
          sidebarOpen ? 'w-64' : 'w-20'
        } flex flex-col`}
      >
        {/* Logo */}
        <div className={`flex items-center justify-between h-16 px-4 border-b border-border-color ${!sidebarOpen && 'justify-center'}`}>
          <div className="flex items-center gap-2">
            <span className="text-2xl">📈</span>
            {sidebarOpen && <span className="font-bold text-xl text-text-primary">StockCalls</span>}
          </div>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 rounded-lg hover:bg-bg-tertiary transition-colors text-text-secondary"
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            {sidebarOpen ? '◀' : '▶'}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {navigation.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) => `
                  flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all
                  ${isActive 
                    ? 'bg-accent-primary/15 text-accent-primary border-l-3 border-accent-primary' 
                    : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary'
                  }
                  ${!sidebarOpen ? 'justify-center px-2' : ''}
                `}
                title={sidebarOpen ? undefined : item.label}
              >
                <span className="text-lg flex-shrink-0">{item.icon}</span>
                {sidebarOpen && <span className="font-medium">{item.label}</span>}
                {isActive && sidebarOpen && (
                  <Badge variant="success" size="sm" className="ml-auto">Active</Badge>
                )}
              </NavLink>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="p-3 border-t border-border-color">
          <div className={`flex items-center gap-3 ${!sidebarOpen && 'justify-center'}`}>
            <div className={`w-8 h-8 rounded-full bg-accent-primary/20 flex items-center justify-center ${!sidebarOpen && 'mx-auto'}`}>
              <span className="text-sm font-medium text-accent-primary">SC</span>
            </div>
            {sidebarOpen && (
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text-primary truncate">StockCalls Pro</p>
                <p className="text-xs text-text-muted">v1.0.0</p>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main 
        className={`flex-1 flex flex-col overflow-hidden transition-all duration-300 ${
          sidebarOpen ? 'ml-64' : 'ml-20'
        }`}
      >
        {/* Top Bar */}
        <header className="h-16 bg-card border-b border-border-color flex items-center justify-between px-6 sticky top-0 z-40">
          <h1 className="text-xl font-semibold text-text-primary">
            {navigation.find(n => n.path === location.pathname)?.label || 'Dashboard'}
          </h1>
          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-bg-secondary rounded-lg text-sm text-text-secondary">
              <span>🟢</span> Live
            </div>
            <div className="w-8 h-8 rounded-full bg-accent-primary/20 flex items-center justify-center">
              <span className="text-sm font-medium text-accent-primary">SC</span>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <div className="flex-1 overflow-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
};
