import { FC, useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';

interface Settings {
  telegram_bot_token: string;
  telegram_chat_id: string;
  alpha_vantage_key: string;
  polygon_key: string;
  finnhub_key: string;
  scan_schedule: string;
  backtest_default_phases: number;
  data_cache_ttl: number;
  log_level: string;
}

interface BaseField {
  key: keyof Settings;
  label: string;
  type: 'text' | 'password' | 'number' | 'select';
  placeholder?: string;
  fullWidth?: boolean;
}

interface TextField extends BaseField {
  type: 'text' | 'password';
  min?: never;
  max?: never;
  options?: never;
}

interface NumberField extends BaseField {
  type: 'number';
  min: number;
  max: number;
  placeholder?: string;
  options?: never;
}

interface SelectField extends BaseField {
  type: 'select';
  options: { value: string; label: string }[];
  placeholder?: string;
  min?: never;
  max?: never;
}

type FormField = TextField | NumberField | SelectField;

interface Section {
  title: string;
  description: string;
  fields: FormField[];
  action?: React.ReactNode;
}


export const Settings: FC = () => {
  const [settings, setSettings] = useState<Settings>({
    telegram_bot_token: '',
    telegram_chat_id: '',
    alpha_vantage_key: '',
    polygon_key: '',
    finnhub_key: '',
    scan_schedule: '0 6 * * *',
    backtest_default_phases: 3,
    data_cache_ttl: 24,
    log_level: 'INFO',
  });
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const response = await fetch('/api/settings');
      if (response.ok) {
        const data = await response.json();
        setSettings(prev => ({ ...prev, ...data }));
      }
    } catch {
      // Use defaults
    }
  };

  const saveSettings = async () => {
    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (response.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      }
    } catch (error) {
      console.error('Failed to save settings:', error);
    }
  };

  const testTelegram = async () => {
    setTesting('telegram');
    try {
      const response = await fetch('/api/test/telegram', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bot_token: settings.telegram_bot_token,
          chat_id: settings.telegram_chat_id,
        }),
      });
      if (response.ok) {
        alert('Telegram test message sent successfully!');
      } else {
        alert('Failed to send test message');
      }
    } catch {
      alert('Error testing Telegram');
    } finally {
      setTesting(null);
    }
  };

  const sections: Section[] = [
    {
      title: 'Telegram Notifications',
      description: 'Configure bot for daily scan alerts and signal notifications',
      fields: [
        { key: 'telegram_bot_token', label: 'Bot Token', type: 'password', placeholder: '123456789:ABCdefGHIjklMNOpqrsTUVwxyz' },
        { key: 'telegram_chat_id', label: 'Chat ID', type: 'text', placeholder: '123456789' },
      ],
      action: (
        <Button variant="outline" size="sm" onClick={testTelegram} disabled={testing === 'telegram'}>
          {testing === 'telegram' ? 'Testing...' : 'Send Test Message'}
        </Button>
      ),
    },
    {
      title: 'Market Data APIs',
      description: 'Optional API keys for enhanced data (free tiers available)',
      fields: [
        { key: 'alpha_vantage_key', label: 'Alpha Vantage', type: 'password', placeholder: 'Free at alphavantage.co' },
        { key: 'polygon_key', label: 'Polygon.io', type: 'password', placeholder: 'Free tier at polygon.io' },
        { key: 'finnhub_key', label: 'Finnhub', type: 'password', placeholder: 'Free at finnhub.io' },
      ],
    },
    {
      title: 'Scheduler',
      description: 'Configure automated scan timing (cron format)',
      fields: [
        { key: 'scan_schedule', label: 'Scan Schedule (Cron)', type: 'text', placeholder: '0 6 * * *' },
        { key: 'backtest_default_phases', label: 'Default Backtest Phases', type: 'number', min: 1, max: 10 },
        { key: 'data_cache_ttl', label: 'Data Cache TTL (hours)', type: 'number', min: 1, max: 168 },
      ],
    },
    {
      title: 'Advanced',
      description: 'System configuration options',
      fields: [
        { key: 'log_level', label: 'Log Level', type: 'select', options: [
          { value: 'DEBUG', label: 'Debug' },
          { value: 'INFO', label: 'Info' },
          { value: 'WARNING', label: 'Warning' },
          { value: 'ERROR', label: 'Error' },
        ] },
      ],
    },
  ];

  const handleChange = (key: string, value: any) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Settings</h1>
          <p className="text-text-secondary">Configure StockCalls behavior and integrations</p>
        </div>
        <Button variant="primary" onClick={saveSettings} className={saved ? 'bg-accent-success' : ''}>
          {saved ? '✓ Saved!' : '💾 Save Settings'}
        </Button>
      </div>

      {sections.map((section) => (
        <Card key={section.title}>
          <CardHeader>
            <CardTitle>{section.title}</CardTitle>
            <CardDescription>{section.description}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {section.fields.map((field) => (
                <div key={field.key} className={field.fullWidth ? 'col-span-full' : ''}>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">
                    {field.label}
                  </label>
                  {field.type === 'select' ? (
                    <Select
                      value={settings[field.key as keyof Settings] as string}
                      onChange={(e) => handleChange(field.key, e.target.value)}
                      options={field.options || []}
                    />
                  ) : (
                    <Input
                      type={field.type}
                      value={settings[field.key as keyof Settings] as string | number}
                      onChange={(e) => handleChange(field.key, field.type === 'number' ? Number(e.target.value) : e.target.value)}
                      placeholder={field.placeholder}
                      min={field.min}
                      max={field.max}
                    />
                  )}
                </div>
              ))}
            </div>
            {section.action && (
              <div className="mt-4 pt-4 border-t border-border-color flex justify-end">
                {section.action}
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
};
