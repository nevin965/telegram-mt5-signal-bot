# 🪟 Windows Startup Guide - Telegram Signal EA

## Quick Reference
- **Project Type**: Telegram Signal Processing + MT5 Trading Automation
- **Language**: Python 3.12.7
- **Platform**: Windows with MetaTrader 5
- **Database**: SQLite (local file)

---

## 🚀 Initial Setup (First Time Only)

### 1. Prerequisites Installation
```powershell
# Install Python 3.12.7 from python.org
# Download and install MetaTrader 5 from MetaQuotes
# Ensure you have a Telegram account
```

### 2. Project Setup
```powershell
# Navigate to project directory
cd telegram-signal-ea

# Install dependencies
pip install -r requirements.txt

# Copy environment template
copy .env.example .env
```

### 3. Configure Environment (.env file)
```bash
# Edit .env with your actual credentials
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=your_phone_number
TELEGRAM_SESSION_NAME=telegram_session

MT5_SERVER=your_broker_server
MT5_LOGIN=your_account_number
MT5_PASSWORD=your_password

OPENAI_API_KEY=your_openai_key

DATABASE_URL=sqlite:///signal_ea.db
LOG_LEVEL=INFO
```

---

## 🧪 Testing Workflow (Step by Step)

### Phase 1: Component Testing
```powershell
# Test 1: Verify installation
python --version
# Should show Python 3.12.7

# Test 2: Run unit tests
python -m pytest tests/unit/ -v
# All tests should pass

# Test 3: Check database setup
python -c "from src.database.models import init_db; init_db(); print('Database OK')"
```

### Phase 2: Connection Testing
```powershell
# Test 4: Telegram connection (first run will ask for phone verification)
python -c "from src.telegram.client import TelegramClient; client = TelegramClient(); print('Telegram OK')"

# Test 5: MT5 connection (MT5 must be running and logged in)
python -c "from src.mt5.connection import MT5Connection; mt5 = MT5Connection(); print('MT5 Connected:', mt5.connect())"

# Test 6: OpenAI API connection
python -c "from src.llm.openai_client import OpenAIClient; client = OpenAIClient(); print('OpenAI OK')"
```

### Phase 3: Signal Processing Testing
```powershell
# Test 7: Signal parsing
python -c "from src.signal_parser.french_parser import FrenchSignalParser; parser = FrenchSignalParser(); print('Parser ready')"

# Test 8: Test with sample signal
python tests/manual_tests/test_signal_sample.py
```

### Phase 4: Integration Testing
```powershell
# Test 9: Full integration test
python -m pytest tests/integration/ -v

# Test 10: End-to-end test (with real but small position)
python tests/manual_tests/test_full_workflow.py
```

---

## 🎯 Production Startup

### Normal Operation
```powershell
# Start the main application
python main.py

# Alternative: Start with console dashboard
python main.py --dashboard

# Alternative: Start in debug mode
python main.py --debug
```

### Monitoring Commands
```powershell
# View live dashboard (separate terminal)
python -c "from src.monitoring.console_dashboard import RichDashboard; dashboard = RichDashboard(); dashboard.run()"

# Check system status
python cli.py --status

# View recent logs
type logs/telegram_ea.log | findstr /C:"ERROR" /C:"WARNING"
```

---

## 🐛 Debugging Guide

### Common Issues & Solutions

#### 1. Telegram Authentication Fails
```powershell
# Delete session file and re-authenticate
del telegram_session.session
python -c "from src.telegram.client import TelegramClient; TelegramClient().start()"
```

#### 2. MT5 Connection Issues
```powershell
# Check MT5 is running and logged in
# Verify .env credentials match MT5 account
# Test connection manually:
python -c "import MetaTrader5 as mt5; print('MT5 Available:', mt5.initialize())"
```

#### 3. Database Errors
```powershell
# Reset database (WARNING: deletes all data)
del signal_ea.db
python -c "from src.database.models import init_db; init_db(); print('Database reset')"
```

#### 4. Signal Parsing Issues
```powershell
# Test signal patterns
python tests/manual_tests/debug_signal_parsing.py

# Check regex patterns
python -c "from src.signal_parser.patterns import SIGNAL_PATTERNS; print(len(SIGNAL_PATTERNS), 'patterns loaded')"
```

#### 5. OpenAI API Issues
```powershell
# Test API key
python -c "import openai; client = openai.OpenAI(); print('Models:', [m.id for m in client.models.list().data[:3]])"
```

### Debug Logging
```powershell
# Enable debug logging (edit .env)
LOG_LEVEL=DEBUG

# View debug logs in real-time
powershell Get-Content logs/telegram_ea.log -Wait | Select-String "DEBUG"
```

### Performance Monitoring
```powershell
# Check system resources
python -c "import psutil; print(f'CPU: {psutil.cpu_percent()}%, RAM: {psutil.virtual_memory().percent}%')"

# Monitor signal processing speed
python -c "from src.monitoring.metrics_collector import MetricsCollector; mc = MetricsCollector(); print(mc.get_performance_stats())"
```

---

## 📊 Health Checks

### Daily Health Check Script
```powershell
# Create and run daily_health_check.py
python daily_health_check.py
```

### Health Check Components
- ✅ Database connectivity
- ✅ Telegram session active
- ✅ MT5 connection status
- ✅ OpenAI API availability
- ✅ Signal queue processing
- ✅ Disk space and memory usage

---

## 🚨 Emergency Procedures

### Emergency Stop
```powershell
# From dashboard console
STOP ALL

# From command line
python -c "from src.utils.emergency_stop import EmergencyStop; EmergencyStop().trigger()"
```

### Safe Shutdown
```powershell
# Graceful shutdown (processes current signals then stops)
Ctrl+C in main terminal

# Force stop (immediate)
taskkill /f /im python.exe
```

### Backup & Recovery
```powershell
# Backup database
copy signal_ea.db signal_ea_backup_%date%.db

# Backup logs
copy logs\telegram_ea.log logs\backup\telegram_ea_%date%.log

# Recovery (restore from backup)
copy signal_ea_backup_YYYY-MM-DD.db signal_ea.db
```

---

## 📁 Important File Locations

```
telegram-signal-ea/
├── main.py                    # Main application entry
├── cli.py                     # Command line interface
├── signal_ea.db              # SQLite database
├── logs/telegram_ea.log      # Application logs
├── .env                      # Environment configuration
├── telegram_session.session  # Telegram session file
└── config/                   # Configuration files
    ├── telegram_config.yaml
    ├── mt5_config.yaml
    └── signal_patterns.yaml
```

---

## 🔧 Development & Testing Tools

### Live Testing
```powershell
# Monitor signal processing
python tools/signal_monitor.py

# Test with fake signals
python tools/signal_simulator.py

# Database viewer
python tools/db_viewer.py
```

### Configuration Validation
```powershell
# Validate all config files
python tools/validate_config.py

# Test signal patterns
python tools/test_patterns.py
```

---

## 📞 Support & Troubleshooting

### Log Analysis
```powershell
# Find errors in logs
findstr /C:"ERROR" logs\telegram_ea.log

# Find correlation issues
findstr /C:"correlation_confidence" logs\telegram_ea.log

# Find trading activity
findstr /C:"TRADE" logs\telegram_ea.log
```

### Common Error Patterns
- `ConnectionError` → Check internet/MT5/Telegram connectivity
- `CorrelationError` → Signal correlation confidence too low
- `DatabaseError` → Database file permissions or corruption
- `ParsingError` → Unknown signal format received

### Performance Optimization
```powershell
# Optimize database
python -c "from src.database.maintenance import optimize_db; optimize_db()"

# Clear old logs (keep last 30 days)
forfiles /p logs /s /m *.log /d -30 /c "cmd /c del @path"
```

---

## ✅ Ready to Use Checklist

Before going live:
- [ ] All tests pass (`pytest tests/`)
- [ ] Environment variables configured
- [ ] Telegram authenticated and connected
- [ ] MT5 running and logged in
- [ ] OpenAI API key working
- [ ] Database initialized
- [ ] Signal patterns loaded
- [ ] Dashboard displays correctly
- [ ] Emergency stop tested
- [ ] Backup procedures verified

**🎉 Your Telegram Signal EA is ready for Windows operation!**