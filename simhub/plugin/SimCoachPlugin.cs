// SimCoach plugin for SimHub: turns SimCoach's live coaching feed into SimCoach.* properties, events and actions
// for DashStudio dashboards, LED profiles, overlays and button boxes.
//
// SimCoach sends one JSON datagram ten times a second to 127.0.0.1:47318; button presses go back to
// 127.0.0.1:47319 as "SIMCOACH-CMD 1 <action> [down|up]". The contract is docs/simhub-link.md in the SimCoach repo.
// Nothing leaves the PC.
//
// Built with the .NET Framework's own C# compiler (C# 5), so: no string interpolation, no ?. and no => members.
// Build: simhub\build_plugin.ps1

using System;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using GameReaderCommon;
using Newtonsoft.Json.Linq;
using SimHub.Plugins;

[assembly: System.Reflection.AssemblyTitle("SimCoach for SimHub")]
[assembly: System.Reflection.AssemblyDescription("Live coaching from SimCoach on SimHub dashboards")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.0.0.0")]

namespace SimCoachSimHub
{
    [PluginDescription("Live coaching from SimCoach: delta, the coach's calls, focus corners, goals, pace against the target, corner losses and buttons for the coach.")]
    [PluginAuthor("SimCoach")]
    [PluginName("SimCoach")]
    public class SimCoach : IPlugin, IDataPlugin, IWPFSettingsV2
    {
        public const int FeedPort = 47318;
        public const int CommandPort = 47319;
        public const string Magic = "SIMCOACH-SIMHUB";
        public const double FreshSeconds = 8.0;     // a coach line counts as "new" this long
        public const int MaxCorners = 30, MaxWorst = 5, MaxLaps = 8, MaxGoals = 3;

        private volatile JObject state;
        private long lastRxTicks;                   // DateTime.UtcNow.Ticks of the last good datagram
        private long packets;
        private Thread rxThread;
        private volatile bool stopping;
        private UdpClient rx;
        private UdpClient tx;

        // what the events last saw
        private string seenCoach;
        private double? seenBest;
        private int seenGoalsDone = -1;
        private bool seenConnected;

        public PluginManager PluginManager { get; set; }

        public ImageSource PictureIcon
        {
            get { return MakeIcon(); }
        }

        public string LeftMenuTitle
        {
            get { return "SimCoach"; }
        }

        // ---- lifecycle --------------------------------------------------------------------------------------
        public void Init(PluginManager pluginManager)
        {
            SimHub.Logging.Current.Info("SimCoach plugin: listening for SimCoach on 127.0.0.1:" + FeedPort);
            DeclareProperties();

            this.AddEvent("CoachLine");       // the coach or crew said something new
            this.AddEvent("NewBestLap");
            this.AddEvent("GoalDone");        // a goal corner from last session is fixed
            this.AddEvent("Connected");       // SimCoach appeared
            this.AddEvent("Disconnected");

            this.AddAction("Repeat", (pm, a) => Send("repeat"), (pm, a) => { });
            this.AddAction("Mute", (pm, a) => Send("mute"), (pm, a) => { });
            this.AddAction("BrakeTones", (pm, a) => Send("tones"), (pm, a) => { });
            this.AddAction("Overlay", (pm, a) => Send("overlay"), (pm, a) => { });
            this.AddAction("SetupSheet", (pm, a) => Send("sheet"), (pm, a) => { });
            this.AddAction("Capture", (pm, a) => Send("capture"), (pm, a) => { });
            this.AddInputMapping("PushToTalk", (pm, a) => Send("ptt down"), (pm, a) => Send("ptt up"));

            try
            {
                tx = new UdpClient();
            }
            catch (Exception e)
            {
                SimHub.Logging.Current.Warn("SimCoach plugin: can't send buttons: " + e.Message);
            }
            stopping = false;
            rxThread = new Thread(ReceiveLoop);
            rxThread.IsBackground = true;
            rxThread.Name = "SimCoach feed";
            rxThread.Start();
        }

        public void End(PluginManager pluginManager)
        {
            stopping = true;
            try { if (rx != null) rx.Close(); } catch (Exception) { }
            try { if (tx != null) tx.Close(); } catch (Exception) { }
        }

        public void DataUpdate(PluginManager pluginManager, ref GameData data)
        {
            // events (cheap: a few comparisons per frame)
            bool conn = Connected();
            if (conn != seenConnected)
            {
                seenConnected = conn;
                this.TriggerEvent(conn ? "Connected" : "Disconnected");
            }
            if (!conn)
                return;
            string coach = S("coach");
            if (coach != null && coach != seenCoach)
            {
                if (seenCoach != null)
                    this.TriggerEvent("CoachLine");
                seenCoach = coach;
            }
            double? best = D("best_s");
            if (best.HasValue && (!seenBest.HasValue || best.Value < seenBest.Value - 0.0005))
            {
                if (seenBest.HasValue)
                    this.TriggerEvent("NewBestLap");
            }
            if (best.HasValue)
                seenBest = best;
            int done = GoalsDone();
            if (seenGoalsDone >= 0 && done > seenGoalsDone)
                this.TriggerEvent("GoalDone");
            seenGoalsDone = done;
        }

        // ---- the feed -----------------------------------------------------------------------------------------
        private void ReceiveLoop()
        {
            while (!stopping)
            {
                try
                {
                    rx = new UdpClient(new IPEndPoint(IPAddress.Loopback, FeedPort));
                    rx.Client.ReceiveTimeout = 1000;
                    SimHub.Logging.Current.Info("SimCoach plugin: waiting for SimCoach");
                    while (!stopping)
                    {
                        IPEndPoint from = new IPEndPoint(IPAddress.Any, 0);
                        byte[] buf;
                        try
                        {
                            buf = rx.Receive(ref from);
                        }
                        catch (SocketException se)
                        {
                            if (se.SocketErrorCode == SocketError.TimedOut || se.SocketErrorCode == SocketError.ConnectionReset)
                                continue;
                            throw;
                        }
                        Accept(buf);
                    }
                }
                catch (Exception e)
                {
                    if (stopping)
                        return;
                    SimHub.Logging.Current.Warn("SimCoach plugin: feed problem (" + e.Message + "), retrying");
                    try { if (rx != null) rx.Close(); } catch (Exception) { }
                    Thread.Sleep(2000);
                }
            }
        }

        /// <summary>Takes one datagram; anything that isn't a SimCoach feed is ignored.</summary>
        public bool Accept(byte[] buf)
        {
            try
            {
                JObject o = JObject.Parse(Encoding.UTF8.GetString(buf));
                JToken m = o["magic"];
                JToken v = o["v"];
                if (m == null || (string)m != Magic || v == null || v.Type != JTokenType.Integer || (int)v < 1)
                    return false;
                state = o;
                Interlocked.Exchange(ref lastRxTicks, DateTime.UtcNow.Ticks);
                Interlocked.Increment(ref packets);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public bool Connected()
        {
            long t = Interlocked.Read(ref lastRxTicks);
            return t != 0 && (DateTime.UtcNow.Ticks - t) < TimeSpan.TicksPerSecond * 3 / 2;
        }

        public void Send(string command)
        {
            if (tx == null)
                return;
            try
            {
                byte[] b = Encoding.ASCII.GetBytes("SIMCOACH-CMD 1 " + command);
                tx.Send(b, b.Length, new IPEndPoint(IPAddress.Loopback, CommandPort));
            }
            catch (Exception)
            {
                // SimCoach not running: nothing to do
            }
        }

        // ---- reading the latest datagram -----------------------------------------------------------------------
        private JToken T(string path)
        {
            JObject o = state;
            if (o == null || !Connected())
                return null;
            try
            {
                JToken t = o.SelectToken(path);
                return (t == null || t.Type == JTokenType.Null) ? null : t;
            }
            catch (Exception)
            {
                return null;
            }
        }

        public string S(string path)
        {
            JToken t = T(path);
            if (t == null)
                return null;
            if (t.Type == JTokenType.Float)
                return ((double)t).ToString(CultureInfo.InvariantCulture);
            return t.ToString();
        }

        public double? D(string path)
        {
            JToken t = T(path);
            if (t == null)
                return null;
            if (t.Type == JTokenType.Float || t.Type == JTokenType.Integer)
                return (double)t;
            double d;
            if (double.TryParse(t.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                return d;
            return null;
        }

        public int? I(string path)
        {
            double? d = D(path);
            return d.HasValue ? (int?)(int)Math.Round(d.Value) : null;
        }

        public bool B(string path)
        {
            JToken t = T(path);
            if (t == null)
                return false;
            if (t.Type == JTokenType.Boolean)
                return (bool)t;
            if (t.Type == JTokenType.Integer || t.Type == JTokenType.Float)
                return (double)t != 0;
            return t.ToString().Length > 0;
        }

        /// <summary>True while a line (coach call, what was heard) is there and less than FreshSeconds old.</summary>
        private bool Fresh(string textKey, string ageKey)
        {
            if (string.IsNullOrEmpty(S(textKey)))
                return false;
            double? a = D(ageKey);
            return a.HasValue && a.Value >= 0 && a.Value < FreshSeconds;
        }

        private int Count(string path)
        {
            JArray a = T(path) as JArray;
            return a == null ? 0 : a.Count;
        }

        private int GoalsDone()
        {
            JArray a = T("goals") as JArray;
            if (a == null)
                return 0;
            int n = 0;
            foreach (JToken g in a)
            {
                JToken d = g["done"];
                if (d != null && d.Type == JTokenType.Boolean && (bool)d)
                    n++;
            }
            return n;
        }

        private static string Signed(double? x, string fmt)
        {
            if (!x.HasValue)
                return null;
            return (x.Value > 0 ? "+" : "") + x.Value.ToString(fmt, CultureInfo.InvariantCulture);
        }

        private string GoalText(int i)
        {
            string p = "goals[" + i + "]";
            int? turn = I(p + ".turn");
            if (!turn.HasValue)
                return null;
            double? change = D(p + ".change");
            int laps = I(p + ".laps") ?? 0;
            string t = "T" + turn.Value + "  ";
            if (B(p + ".done"))
                return t + "DONE " + Signed(change, "0.00") + "s";
            if (change.HasValue && laps >= 2)
                return t + Signed(change, "0.00") + "s vs last";
            double? lost = D(p + ".last_loss");
            return t + (lost.HasValue ? "lost " + lost.Value.ToString("0.00", CultureInfo.InvariantCulture) + "s last time" : "goal");
        }

        private string FocusTurns()
        {
            JArray a = T("focus_turns") as JArray;
            if (a == null || a.Count == 0)
                return null;
            StringBuilder sb = new StringBuilder();
            foreach (JToken t in a)
            {
                if (sb.Length > 0)
                    sb.Append("  ");
                sb.Append("T").Append(t.ToString());
            }
            return sb.ToString();
        }

        private string Drill()
        {
            int? turn = I("drill.turn");
            if (!turn.HasValue)
                return null;
            return "Drill T" + turn.Value + "  lap " + (I("drill.lap") ?? 1) + "/" + (I("drill.of") ?? 1);
        }

        private string Gear()
        {
            int? g = I("gear");
            if (!g.HasValue)
                return null;
            return g.Value > 0 ? g.Value.ToString(CultureInfo.InvariantCulture) : g.Value == 0 ? "N" : "R";
        }

        private void DeclareProperties()
        {
            // link and session
            this.AttachDelegate("Connected", () => Connected());
            this.AttachDelegate("Packets", () => Interlocked.Read(ref packets));
            this.AttachDelegate("Running", () => B("running"));
            this.AttachDelegate("Live", () => B("live"));
            this.AttachDelegate("Version", () => S("version"));
            this.AttachDelegate("Driver", () => S("driver"));
            this.AttachDelegate("Sim", () => S("sim"));
            this.AttachDelegate("Track", () => S("track"));
            this.AttachDelegate("Car", () => S("car"));
            this.AttachDelegate("Status", () => S("status"));

            // live coaching
            this.AttachDelegate("Delta", () => D("delta_s"));
            this.AttachDelegate("DeltaText", () => S("delta_s") == null ? "--.--" : S("delta_text"));
            this.AttachDelegate("DeltaValid", () => D("delta_s").HasValue);
            this.AttachDelegate("Coach", () => S("coach"));
            this.AttachDelegate("CoachAge", () => D("coach_age"));
            this.AttachDelegate("CoachFresh", () => Fresh("coach", "coach_age"));
            this.AttachDelegate("Focus", () => S("focus"));
            this.AttachDelegate("FocusTurns", () => FocusTurns());
            this.AttachDelegate("Goal", () => S("goal"));
            this.AttachDelegate("Heard", () => S("heard"));
            this.AttachDelegate("HeardFresh", () => Fresh("heard", "heard_age"));
            this.AttachDelegate("Talking", () => B("talking"));
            this.AttachDelegate("Muted", () => B("muted"));
            this.AttachDelegate("BrakeTones", () => S("tones"));
            this.AttachDelegate("BrakeTonesOn", () => { string t = S("tones"); return t != null && t != "off"; });
            this.AttachDelegate("Mic", () => S("mic"));
            this.AttachDelegate("Listening", () => S("mic") == "listening");
            this.AttachDelegate("Drill", () => Drill());
            this.AttachDelegate("DrillActive", () => I("drill.turn").HasValue);

            // laps and pace
            this.AttachDelegate("Lap", () => I("lap"));
            this.AttachDelegate("LapsDone", () => I("laps_done"));
            this.AttachDelegate("LastLap", () => S("last"));
            this.AttachDelegate("LastLapSeconds", () => D("last_s"));
            this.AttachDelegate("BestLap", () => S("best"));
            this.AttachDelegate("BestLapSeconds", () => D("best_s"));
            this.AttachDelegate("TheoreticalBest", () => S("theo"));
            this.AttachDelegate("TheoreticalBestSeconds", () => D("theo_s"));
            this.AttachDelegate("TargetLap", () => S("target"));
            this.AttachDelegate("TargetLapSeconds", () => D("target_s"));
            this.AttachDelegate("PacePercent", () => D("pace_pct"));
            this.AttachDelegate("Consistency", () => D("cons_sd"));
            this.AttachDelegate("ConsistencyLabel", () => S("cons_label"));

            // race
            this.AttachDelegate("Position", () => I("pos"));
            this.AttachDelegate("Cars", () => I("cars"));
            this.AttachDelegate("GapAhead", () => D("gap_ahead"));
            this.AttachDelegate("GapBehind", () => D("gap_behind"));
            this.AttachDelegate("Fuel", () => S("fuel"));
            this.AttachDelegate("FuelLaps", () => I("fuel_laps"));
            this.AttachDelegate("Speed", () => I("speed"));
            this.AttachDelegate("Gear", () => Gear());

            // where the time goes: worst corners on the last lap, most time lost first
            this.AttachDelegate("WorstCount", () => Count("worst"));
            for (int i = 0; i < MaxWorst; i++)
            {
                string p = "worst[" + i + "]";
                string n = "Worst" + (i + 1);
                this.AttachDelegate(n + ".Turn", () => I(p + ".turn"));
                this.AttachDelegate(n + ".Loss", () => D(p + ".loss"));
                this.AttachDelegate(n + ".Issue", () => S(p + ".issue"));
            }

            // every corner, by turn number
            this.AttachDelegate("CornerCount", () => Count("corners"));
            for (int i = 0; i < MaxCorners; i++)
            {
                string p = "corners[" + i + "]";
                string n = "Corner" + (i + 1).ToString("00");
                this.AttachDelegate(n + ".Loss", () => D(p + ".loss"));
                this.AttachDelegate(n + ".Issue", () => S(p + ".issue"));
            }

            // recent laps, newest first
            this.AttachDelegate("LapCount", () => Count("laps"));
            for (int i = 0; i < MaxLaps; i++)
            {
                int k = i;
                string n = "Laps" + (i + 1);
                this.AttachDelegate(n + ".Number", () => I(RecentLap(k) + ".n"));
                this.AttachDelegate(n + ".Time", () => S(RecentLap(k) + ".time"));
                this.AttachDelegate(n + ".Seconds", () => D(RecentLap(k) + ".s"));
                this.AttachDelegate(n + ".Gap", () => D(RecentLap(k) + ".gap"));
                this.AttachDelegate(n + ".Flag", () => B(RecentLap(k) + ".pit") ? "PIT" : B(RecentLap(k) + ".invalid") ? "OFF" : "");
            }

            // goals carried over from last session
            this.AttachDelegate("GoalCount", () => Count("goals"));
            this.AttachDelegate("GoalsDone", () => GoalsDone());
            for (int i = 0; i < MaxGoals; i++)
            {
                int k = i;
                string p = "goals[" + i + "]";
                string n = "Goals" + (i + 1);
                this.AttachDelegate(n + ".Turn", () => I(p + ".turn"));
                this.AttachDelegate(n + ".Change", () => D(p + ".change"));
                this.AttachDelegate(n + ".Laps", () => I(p + ".laps"));
                this.AttachDelegate(n + ".Done", () => B(p + ".done"));
                this.AttachDelegate(n + ".Text", () => GoalText(k));
            }
        }

        private string RecentLap(int k)
        {
            int n = Count("laps");
            return "laps[" + Math.Max(-1, n - 1 - k) + "]";
        }

        // ---- the settings page in SimHub ----------------------------------------------------------------------
        public Control GetWPFSettingsControl(PluginManager pluginManager)
        {
            return new SettingsPage(this);
        }

        private static ImageSource MakeIcon()
        {
            // a headset: band, two ear cups and a mic boom, white on transparent (SimHub tints it)
            Geometry g = Geometry.Parse(
                "M4,13 A8,8 0 0 1 20,13 L18,13 A6,6 0 0 0 6,13 Z " +
                "M3,13 L7,13 L7,20 L3,20 Z M17,13 L21,13 L21,20 L17,20 Z " +
                "M19,20 L19,22 L13,22 L13,21 L18,21 L18,20 Z");
            DrawingImage img = new DrawingImage(new GeometryDrawing(Brushes.White, null, g));
            img.Freeze();
            return img;
        }

        public string Describe()
        {
            if (!Connected())
                return Interlocked.Read(ref packets) == 0
                    ? "Waiting for SimCoach. Start SimCoach (6.22 or later); 'Send coaching to SimHub dashboards' is on by default in its Settings."
                    : "SimCoach has stopped sending. Is it still open?";
            string where = S("track") != null ? S("sim") + "  ·  " + S("track") + "  ·  " + S("car") : "waiting for a sim";
            return "Connected to SimCoach " + S("version") + "  ·  " + where;
        }
    }

    public class SettingsPage : UserControl
    {
        private readonly SimCoach plugin;
        private readonly TextBlock status;
        private readonly DispatcherTimer timer;

        public SettingsPage(SimCoach plugin)
        {
            this.plugin = plugin;
            StackPanel p = new StackPanel();
            p.Margin = new Thickness(16);
            p.Children.Add(Text("SimCoach for SimHub", 20, true));
            status = Text("", 14, false);
            status.Margin = new Thickness(0, 8, 0, 12);
            p.Children.Add(status);
            p.Children.Add(Text(
                "Every value is a SimCoach.* property (open the property picker and search for SimCoach). The SimCoach " +
                "dashboard uses them all: open it in Dash Studio.\n\n" +
                "Map these in Controls and events (or on a dashboard button):\n" +
                "  SimCoach.Repeat · SimCoach.Mute · SimCoach.BrakeTones · SimCoach.Overlay · SimCoach.SetupSheet · " +
                "SimCoach.Capture, and the SimCoach.PushToTalk input (hold to talk).\n\n" +
                "Events for LEDs, ShakeIt and sounds: SimCoach.CoachLine, SimCoach.NewBestLap, SimCoach.GoalDone, " +
                "SimCoach.Connected, SimCoach.Disconnected.\n\n" +
                "Everything stays on this PC (UDP 127.0.0.1 ports 47318 and 47319).", 13, false));
            WrapPanel buttons = new WrapPanel();
            buttons.Margin = new Thickness(0, 14, 0, 0);
            buttons.Children.Add(Button("Test: repeat last call", "repeat"));
            buttons.Children.Add(Button("Test: mute / unmute", "mute"));
            p.Children.Add(buttons);
            Content = new ScrollViewer { Content = p, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(500) };
            timer.Tick += delegate { status.Text = plugin.Describe(); };
            Loaded += delegate { status.Text = plugin.Describe(); timer.Start(); };
            Unloaded += delegate { timer.Stop(); };
        }

        private static TextBlock Text(string s, double size, bool bold)
        {
            TextBlock t = new TextBlock();
            t.Text = s;
            t.FontSize = size;
            t.TextWrapping = TextWrapping.Wrap;
            if (bold)
                t.FontWeight = FontWeights.SemiBold;
            return t;
        }

        private System.Windows.Controls.Button Button(string label, string command)
        {
            System.Windows.Controls.Button b = new System.Windows.Controls.Button();
            b.Content = label;
            b.Margin = new Thickness(0, 0, 8, 8);
            b.Padding = new Thickness(12, 4, 12, 4);
            b.Click += delegate { plugin.Send(command); };
            return b;
        }
    }
}
