/* ============================================================
 * Premier League 2026/27 Monte Carlo Simulator (C)
 * Time-decay history + multi-team split + player form
 * Build: gcc -O3 -o premierleague.exe premierleague.c -lm
 * ============================================================ */

#ifdef _WIN32
  #include <windows.h>
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <ctype.h>

#define N_SIMS 10000
#define MAX_GOALS 10
#define NUM_TEAMS 20

/* Configuration */
#define ATTACK_SENS 0.10
#define DEFENCE_SENS 0.10

/* Attack weights (4 independent inputs, sum = 1.00) */
#define W_ATT_NPXG          0.55
#define W_ATT_DEEP          0.20
#define W_ATT_PPDA_ALLOWED  0.15
#define W_ATT_XPTS          0.10

/* Defence weights (4 independent inputs, sum = 1.00) */
#define W_DEF_NPXGA         0.55
#define W_DEF_DEEP_ALLOWED  0.20
#define W_DEF_PPDA          0.15
#define W_DEF_XGA           0.10

/* Player-derived attack blend */
#define PLAYER_ATT_WEIGHT 0.12
#define PLAYER_MIN_MINS   90
#define PLAYER_XG90_CAP   1.50
#define PLAYER_XA90_CAP   1.50

/* Season decay weights */
#define SEASON_DECAY   0.60
#define N_HIST_SEASONS 2

static const double SEASON_WEIGHT[3] = {
    1.0,                              /* 2026 current */
    SEASON_DECAY,                     /* 2025 */
    SEASON_DECAY * SEASON_DECAY       /* 2024 */
};

/* Player form factor clip range */
#define FORM_MIN 0.70
#define FORM_MAX 1.40

/* Elo pool */
#define ELO_POOL        20000.0
#define ELO_HALF        (ELO_POOL / 2.0)
#define ELO_PER_SIDE    (ELO_HALF / NUM_TEAMS)
#define ELO_SCALE       400.0
#define ELO_COMPRESS    0.55
#define ELO_SHARE_K     0.50

/* Team names */
static const char *TEAMS[NUM_TEAMS] = {
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton",
    "Chelsea", "Coventry", "Crystal Palace", "Everton", "Fulham",
    "Hull", "Ipswich", "Leeds", "Liverpool", "Man City",
    "Man United", "Newcastle", "Nott'm Forest", "Sunderland", "Tottenham"
};

/* CSV name mapping */
typedef struct { const char *csv_name; const char *script_name; } NameMap;
static const NameMap NAME_MAP[] = {
    {"Manchester City", "Man City"},
    {"Manchester United", "Man United"},
    {"Manchester Utd", "Man United"},
    {"Newcastle United", "Newcastle"},
    {"Newcastle Utd", "Newcastle"},
    {"Nottingham Forest", "Nott'm Forest"},
    {"Nottm Forest", "Nott'm Forest"},
    {"Ipswich Town", "Ipswich"},
    {"Hull City", "Hull"},
    {"Coventry City", "Coventry"},
    {"Leeds Utd", "Leeds"},
    {"Tottenham Hotspur", "Tottenham"},
    {"West Ham", "West Ham"},
    {"Burnley", "Burnley"},
    {"Wolverhampton Wanderers", "Wolves"},
    {"Leicester", "Leicester"},
    {"Southampton", "Southampton"},
    {NULL, NULL}
};

/* Stats structures */
typedef struct {
    int matches;
    double xG, NPxG, xGA, NPxGA, NPxGD;
    double deep, deep_allowed, xPTS;
    double ppda, ppda_allowed;
    int wins, draws, loses, goals, ga, points;
    int has_data;
} TeamStats;

typedef struct {
    double xG, NPxG, xGA, NPxGA, NPxGD;
    double deep, deep_allowed, xPTS;
    double ppda, ppda_allowed;
} BlendedStats;

typedef struct { double attack, defence; } Strengths;

typedef struct {
    int h_idx, a_idx;
    double lam_h, lam_a;
    char date[32];
    char time[8];
    double cum_h[MAX_GOALS + 1];
    double cum_a[MAX_GOALS + 1];
} Fixture;

/* Global state */
static TeamStats current_stats[NUM_TEAMS];
static TeamStats hist_stats[N_HIST_SEASONS][NUM_TEAMS]; /* [0]=2025, [1]=2024 */
static BlendedStats blended_stats[NUM_TEAMS];
static Strengths strengths[NUM_TEAMS];

/* Elo ratings */
static double elo_attack[NUM_TEAMS];
static double elo_defence[NUM_TEAMS];
static double elo_combined[NUM_TEAMS];

/* ============================================================
 * PLAYER FORM TRACKING
 * ============================================================ */
#define MAX_FORM_PLAYERS 1500

typedef struct {
    char   name[64];
    double comb_2026;
    double comb_2025;
    int    has_2026;
    int    has_2025;
} PlayerFormEntry;

static PlayerFormEntry player_form[MAX_FORM_PLAYERS];
static int n_player_form = 0;

static PlayerFormEntry *find_player_form(const char *name) {
    for (int i = 0; i < n_player_form; i++)
        if (strcmp(player_form[i].name, name) == 0) return &player_form[i];
    return NULL;
}

static PlayerFormEntry *find_or_create_player_form(const char *name) {
    PlayerFormEntry *e = find_player_form(name);
    if (e) return e;
    if (n_player_form >= MAX_FORM_PLAYERS) return NULL;
    e = &player_form[n_player_form++];
    strncpy(e->name, name, sizeof(e->name) - 1);
    e->name[sizeof(e->name) - 1] = '\0';
    e->comb_2026 = 0.0;
    e->comb_2025 = 0.0;
    e->has_2026 = 0;
    e->has_2025 = 0;
    return e;
}

/* ============================================================
 * PLAYER-DERIVED TEAM AGGREGATES
 * ============================================================ */
typedef struct {
    double sum_xG90;
    double sum_xA90;
    double sum_xG90xA90;
    double top_xG90;
    double top_xA90;
    char   top_scorer[64];
    char   top_creator[64];
    int    n_players;
    int    n_att;
    double star_share;
    int    has_data;
} TeamPlayerAgg;

static TeamPlayerAgg team_players[NUM_TEAMS];
static double        player_att_z[NUM_TEAMS];

/* Live table state */
static int cur_pts[NUM_TEAMS], cur_w[NUM_TEAMS], cur_d[NUM_TEAMS], cur_l[NUM_TEAMS];
static int cur_gf[NUM_TEAMS], cur_ga[NUM_TEAMS], cur_gd[NUM_TEAMS];

/* Head-to-head tracking */
static int h2h_points[NUM_TEAMS][NUM_TEAMS];
static int h2h_gf[NUM_TEAMS][NUM_TEAMS];
static int h2h_ga[NUM_TEAMS][NUM_TEAMS];

static Fixture remaining_fixtures[400];
static int n_remaining = 0;

/* Simulation accumulators */
static long long title_c[NUM_TEAMS], top4_c[NUM_TEAMS], fifth_c[NUM_TEAMS];
static long long top6_c[NUM_TEAMS], rel_c[NUM_TEAMS];
static double pts_sum[NUM_TEAMS], gf_sum[NUM_TEAMS], ga_sum[NUM_TEAMS], pos_sum[NUM_TEAMS];
static long long win_c[NUM_TEAMS], draw_c[NUM_TEAMS], loss_c[NUM_TEAMS];
static int sims_done = 0;

/* ============================================================
 * COMPLETED MATCHES
 * ============================================================ */
typedef struct { const char *h, *a; int hg, ag; } RawResult;
static const RawResult COMPLETED[] = {
    {"Arsenal", "Coventry", 3, 0}, {"Hull", "Man United", 2, 0},
    {"Everton", "Crystal Palace", 2, 0}, {"Ipswich", "Sunderland", 2, 1},
    {"Nott'm Forest", "Leeds", 0, 1}, {"Brentford", "Tottenham", 3, 0},
    {"Brighton", "Aston Villa", 4, 0}, {"Man City", "Bournemouth", 2, 1},
    {"Newcastle", "Liverpool", 2, 2}, {"Fulham", "Chelsea", 2, 3},
    {"Crystal Palace", "Man City", 1, 4}, {"Liverpool", "Nott'm Forest", 2, 2},
    {"Bournemouth", "Everton", 1, 1}, {"Coventry", "Hull", 0, 1},
    {"Tottenham", "Newcastle", 0, 2}, {"Chelsea", "Brighton", 4, 3},
    {"Leeds", "Brentford", 1, 1}, {"Sunderland", "Fulham", 1, 0},
    {"Man United", "Ipswich", 5, 2}, {"Aston Villa", "Arsenal", 0, 1},
    {"Ipswich", "Liverpool", 0, 2}, {"Newcastle", "Bournemouth", 2, 2},
    {"Brentford", "Sunderland", 1, 1}, {"Brighton", "Leeds", 1, 1},
    {"Fulham", "Crystal Palace", 2, 3}, {"Man City", "Coventry", 1, 0},
    {"Nott'm Forest", "Tottenham", 0, 0}, {"Hull", "Aston Villa", 0, 0},
    {"Everton", "Man United", 2, 2}, {"Arsenal", "Chelsea", 2, 1},
    {"Bournemouth", "Brentford", 2, 2}, {"Aston Villa", "Nott'm Forest", 1, 2},
    {"Chelsea", "Hull", 2, 2}, {"Crystal Palace", "Ipswich", 2, 3},
    {"Liverpool", "Fulham", 0, 0}, {"Tottenham", "Everton", 0, 0},
    {"Sunderland", "Arsenal", 0, 2}, {"Brighton", "Coventry", 5, 0},
    {"Man City", "Man United", 1, 0}, {"Leeds", "Newcastle", 4, 1},
    {"Brentford", "Chelsea", 3, 0},
    {"Tottenham", "Aston Villa", 2, 3},
    {"Newcastle", "Hull", 2, 1},
    {"Brighton", "Arsenal", 3, 0},
    {"Everton", "Ipswich", 1, 0},
    {"Nott'm Forest", "Coventry", 0, 1},
    {"Bournemouth", "Liverpool", 0, 1},
    {"Leeds", "Crystal Palace", 0, 0},
    {"Man City", "Sunderland", 5, 3},
    {"Fulham", "Man United", 1, 1}
};
#define N_COMPLETED ((int)(sizeof(COMPLETED) / sizeof(COMPLETED[0])))

/* ============================================================
 * REMAINING SCHEDULE
 * ============================================================ */
typedef struct {
    const char *date, *time, *home, *away;
} ScheduledFixture;

static const ScheduledFixture REMAINING[] = {
    {"Sat 10 Oct", "12:30", "Arsenal", "Leeds"},
    {"Sat 10 Oct", "15:00", "Aston Villa", "Brentford"},
    {"Sat 10 Oct", "15:00", "Chelsea", "Bournemouth"},
    {"Sat 10 Oct", "15:00", "Ipswich", "Fulham"},
    {"Sat 10 Oct", "15:00", "Sunderland", "Brighton"},
    {"Sat 10 Oct", "17:30", "Man United", "Tottenham"},
    {"Sun 11 Oct", "14:00", "Crystal Palace", "Nott'm Forest"},
    {"Sun 11 Oct", "14:00", "Hull", "Everton"},
    {"Sun 11 Oct", "16:30", "Liverpool", "Man City"},
    {"Mon 12 Oct", "20:00", "Coventry", "Newcastle"},

    {"Sat 17 Oct", "12:30", "Everton", "Chelsea"},
    {"Sat 17 Oct", "15:00", "Brentford", "Liverpool"},
    {"Sat 17 Oct", "15:00", "Fulham", "Hull"},
    {"Sat 17 Oct", "15:00", "Man City", "Ipswich"},
    {"Sat 17 Oct", "17:30", "Newcastle", "Aston Villa"},
    {"Sun 18 Oct", "14:00", "Bournemouth", "Sunderland"},
    {"Sun 18 Oct", "14:00", "Brighton", "Crystal Palace"},
    {"Sun 18 Oct", "14:00", "Leeds", "Man United"},
    {"Sun 18 Oct", "16:30", "Nott'm Forest", "Arsenal"},
    {"Mon 19 Oct", "20:00", "Tottenham", "Coventry"},

    {"Fri 23 Oct", "20:00", "Ipswich", "Nott'm Forest"},
    {"Sat 24 Oct", "12:30", "Aston Villa", "Man City"},
    {"Sat 24 Oct", "15:00", "Arsenal", "Everton"},
    {"Sat 24 Oct", "15:00", "Coventry", "Fulham"},
    {"Sat 24 Oct", "17:30", "Chelsea", "Tottenham"},
    {"Sun 25 Oct", "15:00", "Crystal Palace", "Newcastle"},
    {"Sun 25 Oct", "15:00", "Hull", "Brentford"},
    {"Sun 25 Oct", "15:00", "Liverpool", "Brighton"},
    {"Sun 25 Oct", "15:00", "Man United", "Bournemouth"},
    {"Sun 25 Oct", "17:30", "Sunderland", "Leeds"},

    {"Sat 31 Oct", "13:30", "Chelsea", "Man United"},
    {"Sat 31 Oct", "16:00", "Bournemouth", "Leeds"},
    {"Sat 31 Oct", "16:00", "Brentford", "Nott'm Forest"},
    {"Sat 31 Oct", "16:00", "Coventry", "Sunderland"},
    {"Sat 31 Oct", "16:00", "Hull", "Ipswich"},
    {"Sat 31 Oct", "16:00", "Man City", "Brighton"},
    {"Sat 31 Oct", "18:30", "Tottenham", "Crystal Palace"},
    {"Sat 31 Oct", "21:00", "Aston Villa", "Fulham"},
    {"Sun 1 Nov", "17:30", "Liverpool", "Arsenal"},
    {"Mon 2 Nov", "21:00", "Newcastle", "Everton"},

    {"Sat 7 Nov", "16:00", "Arsenal", "Hull"},
    {"Sat 7 Nov", "16:00", "Brighton", "Brentford"},
    {"Sat 7 Nov", "16:00", "Crystal Palace", "Liverpool"},
    {"Sat 7 Nov", "16:00", "Everton", "Coventry"},
    {"Sat 7 Nov", "16:00", "Fulham", "Newcastle"},
    {"Sat 7 Nov", "16:00", "Ipswich", "Bournemouth"},
    {"Sat 7 Nov", "16:00", "Leeds", "Tottenham"},
    {"Sat 7 Nov", "16:00", "Man United", "Aston Villa"},
    {"Sat 7 Nov", "16:00", "Nott'm Forest", "Man City"},
    {"Sat 7 Nov", "16:00", "Sunderland", "Chelsea"},

    {"Sat 21 Nov", "16:00", "Aston Villa", "Sunderland"},
    {"Sat 21 Nov", "16:00", "Bournemouth", "Nott'm Forest"},
    {"Sat 21 Nov", "16:00", "Brentford", "Everton"},
    {"Sat 21 Nov", "16:00", "Chelsea", "Leeds"},
    {"Sat 21 Nov", "16:00", "Coventry", "Crystal Palace"},
    {"Sat 21 Nov", "16:00", "Hull", "Brighton"},
    {"Sat 21 Nov", "16:00", "Liverpool", "Man United"},
    {"Sat 21 Nov", "16:00", "Man City", "Fulham"},
    {"Sat 21 Nov", "16:00", "Newcastle", "Arsenal"},
    {"Sat 21 Nov", "16:00", "Tottenham", "Ipswich"},

    {"Sat 28 Nov", "16:00", "Arsenal", "Man City"},
    {"Sat 28 Nov", "16:00", "Brighton", "Newcastle"},
    {"Sat 28 Nov", "16:00", "Crystal Palace", "Hull"},
    {"Sat 28 Nov", "16:00", "Everton", "Liverpool"},
    {"Sat 28 Nov", "16:00", "Fulham", "Bournemouth"},
    {"Sat 28 Nov", "16:00", "Ipswich", "Aston Villa"},
    {"Sat 28 Nov", "16:00", "Leeds", "Coventry"},
    {"Sat 28 Nov", "16:00", "Man United", "Brentford"},
    {"Sat 28 Nov", "16:00", "Nott'm Forest", "Chelsea"},
    {"Sat 28 Nov", "16:00", "Sunderland", "Tottenham"},

    {"Wed 2 Dec", "21:00", "Aston Villa", "Everton"},
    {"Wed 2 Dec", "21:00", "Bournemouth", "Brighton"},
    {"Wed 2 Dec", "21:00", "Brentford", "Arsenal"},
    {"Wed 2 Dec", "21:00", "Chelsea", "Crystal Palace"},
    {"Wed 2 Dec", "21:00", "Coventry", "Ipswich"},
    {"Wed 2 Dec", "21:00", "Hull", "Nott'm Forest"},
    {"Wed 2 Dec", "21:00", "Liverpool", "Sunderland"},
    {"Wed 2 Dec", "21:00", "Man City", "Leeds"},
    {"Wed 2 Dec", "21:00", "Newcastle", "Man United"},
    {"Wed 2 Dec", "21:00", "Tottenham", "Fulham"},

    {"Sat 5 Dec", "16:00", "Aston Villa", "Crystal Palace"},
    {"Sat 5 Dec", "16:00", "Bournemouth", "Hull"},
    {"Sat 5 Dec", "16:00", "Brentford", "Man City"},
    {"Sat 5 Dec", "16:00", "Chelsea", "Liverpool"},
    {"Sat 5 Dec", "16:00", "Everton", "Fulham"},
    {"Sat 5 Dec", "16:00", "Leeds", "Ipswich"},
    {"Sat 5 Dec", "16:00", "Man United", "Coventry"},
    {"Sat 5 Dec", "16:00", "Newcastle", "Sunderland"},
    {"Sat 5 Dec", "16:00", "Nott'm Forest", "Brighton"},
    {"Sat 5 Dec", "16:00", "Tottenham", "Arsenal"},

    {"Sat 12 Dec", "16:00", "Arsenal", "Bournemouth"},
    {"Sat 12 Dec", "16:00", "Brighton", "Everton"},
    {"Sat 12 Dec", "16:00", "Coventry", "Aston Villa"},
    {"Sat 12 Dec", "16:00", "Crystal Palace", "Man United"},
    {"Sat 12 Dec", "16:00", "Fulham", "Brentford"},
    {"Sat 12 Dec", "16:00", "Hull", "Tottenham"},
    {"Sat 12 Dec", "16:00", "Ipswich", "Newcastle"},
    {"Sat 12 Dec", "16:00", "Liverpool", "Leeds"},
    {"Sat 12 Dec", "16:00", "Man City", "Chelsea"},
    {"Sat 12 Dec", "16:00", "Sunderland", "Nott'm Forest"},

    {"Sat 19 Dec", "16:00", "Arsenal", "Man United"},
    {"Sat 19 Dec", "16:00", "Bournemouth", "Coventry"},
    {"Sat 19 Dec", "16:00", "Brentford", "Newcastle"},
    {"Sat 19 Dec", "16:00", "Brighton", "Ipswich"},
    {"Sat 19 Dec", "16:00", "Chelsea", "Aston Villa"},
    {"Sat 19 Dec", "16:00", "Leeds", "Fulham"},
    {"Sat 19 Dec", "16:00", "Liverpool", "Tottenham"},
    {"Sat 19 Dec", "16:00", "Man City", "Hull"},
    {"Sat 19 Dec", "16:00", "Nott'm Forest", "Everton"},
    {"Sat 19 Dec", "16:00", "Sunderland", "Crystal Palace"},

    {"Sat 26 Dec", "16:00", "Aston Villa", "Leeds"},
    {"Sat 26 Dec", "16:00", "Coventry", "Chelsea"},
    {"Sat 26 Dec", "16:00", "Crystal Palace", "Arsenal"},
    {"Sat 26 Dec", "16:00", "Everton", "Sunderland"},
    {"Sat 26 Dec", "16:00", "Fulham", "Brighton"},
    {"Sat 26 Dec", "16:00", "Hull", "Liverpool"},
    {"Sat 26 Dec", "16:00", "Ipswich", "Brentford"},
    {"Sat 26 Dec", "16:00", "Man United", "Nott'm Forest"},
    {"Sat 26 Dec", "16:00", "Newcastle", "Man City"},
    {"Sat 26 Dec", "16:00", "Tottenham", "Bournemouth"},

    {"Wed 30 Dec", "21:00", "Aston Villa", "Liverpool"},
    {"Wed 30 Dec", "21:00", "Coventry", "Brentford"},
    {"Wed 30 Dec", "21:00", "Crystal Palace", "Bournemouth"},
    {"Wed 30 Dec", "21:00", "Everton", "Man City"},
    {"Wed 30 Dec", "21:00", "Fulham", "Arsenal"},
    {"Wed 30 Dec", "21:00", "Hull", "Leeds"},
    {"Wed 30 Dec", "21:00", "Ipswich", "Chelsea"},
    {"Wed 30 Dec", "21:00", "Man United", "Sunderland"},
    {"Wed 30 Dec", "21:00", "Newcastle", "Nott'm Forest"},
    {"Wed 30 Dec", "21:00", "Tottenham", "Brighton"},

    {"Sat 2 Jan", "16:00", "Arsenal", "Ipswich"},
    {"Sat 2 Jan", "16:00", "Bournemouth", "Aston Villa"},
    {"Sat 2 Jan", "16:00", "Brentford", "Crystal Palace"},
    {"Sat 2 Jan", "16:00", "Brighton", "Man United"},
    {"Sat 2 Jan", "16:00", "Chelsea", "Newcastle"},
    {"Sat 2 Jan", "16:00", "Leeds", "Everton"},
    {"Sat 2 Jan", "16:00", "Liverpool", "Coventry"},
    {"Sat 2 Jan", "16:00", "Man City", "Tottenham"},
    {"Sat 2 Jan", "16:00", "Nott'm Forest", "Fulham"},
    {"Sat 2 Jan", "16:00", "Sunderland", "Hull"},

    {"Wed 6 Jan", "21:00", "Arsenal", "Brentford"},
    {"Wed 6 Jan", "21:00", "Brighton", "Bournemouth"},
    {"Wed 6 Jan", "21:00", "Crystal Palace", "Chelsea"},
    {"Wed 6 Jan", "21:00", "Everton", "Aston Villa"},
    {"Wed 6 Jan", "21:00", "Fulham", "Tottenham"},
    {"Wed 6 Jan", "21:00", "Ipswich", "Coventry"},
    {"Wed 6 Jan", "21:00", "Leeds", "Man City"},
    {"Wed 6 Jan", "21:00", "Man United", "Newcastle"},
    {"Wed 6 Jan", "21:00", "Nott'm Forest", "Hull"},
    {"Wed 6 Jan", "21:00", "Sunderland", "Liverpool"},

    {"Sat 16 Jan", "16:00", "Aston Villa", "Man United"},
    {"Sat 16 Jan", "16:00", "Bournemouth", "Ipswich"},
    {"Sat 16 Jan", "16:00", "Brentford", "Brighton"},
    {"Sat 16 Jan", "16:00", "Chelsea", "Sunderland"},
    {"Sat 16 Jan", "16:00", "Coventry", "Everton"},
    {"Sat 16 Jan", "16:00", "Hull", "Arsenal"},
    {"Sat 16 Jan", "16:00", "Liverpool", "Crystal Palace"},
    {"Sat 16 Jan", "16:00", "Man City", "Nott'm Forest"},
    {"Sat 16 Jan", "16:00", "Newcastle", "Fulham"},
    {"Sat 16 Jan", "16:00", "Tottenham", "Leeds"},

    {"Sat 23 Jan", "16:00", "Arsenal", "Newcastle"},
    {"Sat 23 Jan", "16:00", "Brighton", "Man City"},
    {"Sat 23 Jan", "16:00", "Crystal Palace", "Tottenham"},
    {"Sat 23 Jan", "16:00", "Everton", "Brentford"},
    {"Sat 23 Jan", "16:00", "Fulham", "Aston Villa"},
    {"Sat 23 Jan", "16:00", "Ipswich", "Hull"},
    {"Sat 23 Jan", "16:00", "Leeds", "Chelsea"},
    {"Sat 23 Jan", "16:00", "Man United", "Liverpool"},
    {"Sat 23 Jan", "16:00", "Nott'm Forest", "Bournemouth"},
    {"Sat 23 Jan", "16:00", "Sunderland", "Coventry"},

    {"Sat 30 Jan", "16:00", "Aston Villa", "Ipswich"},
    {"Sat 30 Jan", "16:00", "Bournemouth", "Fulham"},
    {"Sat 30 Jan", "16:00", "Brentford", "Man United"},
    {"Sat 30 Jan", "16:00", "Chelsea", "Nott'm Forest"},
    {"Sat 30 Jan", "16:00", "Coventry", "Leeds"},
    {"Sat 30 Jan", "16:00", "Hull", "Crystal Palace"},
    {"Sat 30 Jan", "16:00", "Liverpool", "Everton"},
    {"Sat 30 Jan", "16:00", "Man City", "Arsenal"},
    {"Sat 30 Jan", "16:00", "Newcastle", "Brighton"},
    {"Sat 30 Jan", "16:00", "Tottenham", "Sunderland"},

    {"Sat 6 Feb", "16:00", "Arsenal", "Liverpool"},
    {"Sat 6 Feb", "16:00", "Brighton", "Hull"},
    {"Sat 6 Feb", "16:00", "Crystal Palace", "Coventry"},
    {"Sat 6 Feb", "16:00", "Everton", "Newcastle"},
    {"Sat 6 Feb", "16:00", "Fulham", "Man City"},
    {"Sat 6 Feb", "16:00", "Ipswich", "Tottenham"},
    {"Sat 6 Feb", "16:00", "Leeds", "Bournemouth"},
    {"Sat 6 Feb", "16:00", "Man United", "Chelsea"},
    {"Sat 6 Feb", "16:00", "Nott'm Forest", "Brentford"},
    {"Sat 6 Feb", "16:00", "Sunderland", "Aston Villa"},

    {"Wed 10 Feb", "21:00", "Aston Villa", "Bournemouth"},
    {"Wed 10 Feb", "21:00", "Coventry", "Liverpool"},
    {"Wed 10 Feb", "21:00", "Crystal Palace", "Brentford"},
    {"Wed 10 Feb", "21:00", "Everton", "Leeds"},
    {"Wed 10 Feb", "21:00", "Fulham", "Nott'm Forest"},
    {"Wed 10 Feb", "21:00", "Hull", "Sunderland"},
    {"Wed 10 Feb", "21:00", "Ipswich", "Arsenal"},
    {"Wed 10 Feb", "21:00", "Man United", "Brighton"},
    {"Wed 10 Feb", "21:00", "Newcastle", "Chelsea"},
    {"Wed 10 Feb", "21:00", "Tottenham", "Man City"},

    {"Sat 20 Feb", "16:00", "Arsenal", "Fulham"},
    {"Sat 20 Feb", "16:00", "Bournemouth", "Crystal Palace"},
    {"Sat 20 Feb", "16:00", "Brentford", "Coventry"},
    {"Sat 20 Feb", "16:00", "Brighton", "Tottenham"},
    {"Sat 20 Feb", "16:00", "Chelsea", "Ipswich"},
    {"Sat 20 Feb", "16:00", "Leeds", "Aston Villa"},
    {"Sat 20 Feb", "16:00", "Liverpool", "Hull"},
    {"Sat 20 Feb", "16:00", "Man City", "Newcastle"},
    {"Sat 20 Feb", "16:00", "Nott'm Forest", "Man United"},
    {"Sat 20 Feb", "16:00", "Sunderland", "Everton"},

    {"Sat 27 Feb", "16:00", "Aston Villa", "Chelsea"},
    {"Sat 27 Feb", "16:00", "Coventry", "Bournemouth"},
    {"Sat 27 Feb", "16:00", "Crystal Palace", "Sunderland"},
    {"Sat 27 Feb", "16:00", "Everton", "Nott'm Forest"},
    {"Sat 27 Feb", "16:00", "Fulham", "Leeds"},
    {"Sat 27 Feb", "16:00", "Hull", "Man City"},
    {"Sat 27 Feb", "16:00", "Ipswich", "Brighton"},
    {"Sat 27 Feb", "16:00", "Man United", "Arsenal"},
    {"Sat 27 Feb", "16:00", "Newcastle", "Brentford"},
    {"Sat 27 Feb", "16:00", "Tottenham", "Liverpool"},

    {"Wed 3 Mar", "21:00", "Arsenal", "Crystal Palace"},
    {"Wed 3 Mar", "21:00", "Bournemouth", "Tottenham"},
    {"Wed 3 Mar", "21:00", "Brentford", "Ipswich"},
    {"Wed 3 Mar", "21:00", "Brighton", "Fulham"},
    {"Wed 3 Mar", "21:00", "Chelsea", "Coventry"},
    {"Wed 3 Mar", "21:00", "Leeds", "Hull"},
    {"Wed 3 Mar", "21:00", "Liverpool", "Aston Villa"},
    {"Wed 3 Mar", "21:00", "Man City", "Everton"},
    {"Wed 3 Mar", "21:00", "Nott'm Forest", "Newcastle"},
    {"Wed 3 Mar", "21:00", "Sunderland", "Man United"},

    {"Sat 13 Mar", "16:00", "Aston Villa", "Hull"},
    {"Sat 13 Mar", "16:00", "Bournemouth", "Newcastle"},
    {"Sat 13 Mar", "16:00", "Chelsea", "Arsenal"},
    {"Sat 13 Mar", "16:00", "Coventry", "Man City"},
    {"Sat 13 Mar", "16:00", "Crystal Palace", "Fulham"},
    {"Sat 13 Mar", "16:00", "Leeds", "Brighton"},
    {"Sat 13 Mar", "16:00", "Liverpool", "Ipswich"},
    {"Sat 13 Mar", "16:00", "Man United", "Everton"},
    {"Sat 13 Mar", "16:00", "Sunderland", "Brentford"},
    {"Sat 13 Mar", "16:00", "Tottenham", "Nott'm Forest"},

    {"Sat 20 Mar", "16:00", "Arsenal", "Sunderland"},
    {"Sat 20 Mar", "16:00", "Brentford", "Bournemouth"},
    {"Sat 20 Mar", "16:00", "Brighton", "Coventry"},
    {"Sat 20 Mar", "16:00", "Everton", "Tottenham"},
    {"Sat 20 Mar", "16:00", "Fulham", "Liverpool"},
    {"Sat 20 Mar", "16:00", "Hull", "Chelsea"},
    {"Sat 20 Mar", "16:00", "Ipswich", "Crystal Palace"},
    {"Sat 20 Mar", "16:00", "Man City", "Man United"},
    {"Sat 20 Mar", "16:00", "Newcastle", "Leeds"},
    {"Sat 20 Mar", "16:00", "Nott'm Forest", "Aston Villa"},

    {"Sat 10 Apr", "15:00", "Aston Villa", "Brighton"},
    {"Sat 10 Apr", "15:00", "Bournemouth", "Man City"},
    {"Sat 10 Apr", "15:00", "Chelsea", "Fulham"},
    {"Sat 10 Apr", "15:00", "Coventry", "Arsenal"},
    {"Sat 10 Apr", "15:00", "Crystal Palace", "Everton"},
    {"Sat 10 Apr", "15:00", "Leeds", "Nott'm Forest"},
    {"Sat 10 Apr", "15:00", "Liverpool", "Newcastle"},
    {"Sat 10 Apr", "15:00", "Man United", "Hull"},
    {"Sat 10 Apr", "15:00", "Sunderland", "Ipswich"},
    {"Sat 10 Apr", "15:00", "Tottenham", "Brentford"},

    {"Sat 17 Apr", "15:00", "Arsenal", "Aston Villa"},
    {"Sat 17 Apr", "15:00", "Brentford", "Leeds"},
    {"Sat 17 Apr", "15:00", "Brighton", "Chelsea"},
    {"Sat 17 Apr", "15:00", "Everton", "Bournemouth"},
    {"Sat 17 Apr", "15:00", "Fulham", "Sunderland"},
    {"Sat 17 Apr", "15:00", "Hull", "Coventry"},
    {"Sat 17 Apr", "15:00", "Ipswich", "Man United"},
    {"Sat 17 Apr", "15:00", "Man City", "Crystal Palace"},
    {"Sat 17 Apr", "15:00", "Newcastle", "Tottenham"},
    {"Sat 17 Apr", "15:00", "Nott'm Forest", "Liverpool"},

    {"Sat 24 Apr", "15:00", "Aston Villa", "Coventry"},
    {"Sat 24 Apr", "15:00", "Bournemouth", "Arsenal"},
    {"Sat 24 Apr", "15:00", "Brentford", "Fulham"},
    {"Sat 24 Apr", "15:00", "Chelsea", "Man City"},
    {"Sat 24 Apr", "15:00", "Everton", "Brighton"},
    {"Sat 24 Apr", "15:00", "Leeds", "Liverpool"},
    {"Sat 24 Apr", "15:00", "Man United", "Crystal Palace"},
    {"Sat 24 Apr", "15:00", "Newcastle", "Ipswich"},
    {"Sat 24 Apr", "15:00", "Nott'm Forest", "Sunderland"},
    {"Sat 24 Apr", "15:00", "Tottenham", "Hull"},

    {"Sat 1 May", "15:00", "Arsenal", "Tottenham"},
    {"Sat 1 May", "15:00", "Brighton", "Nott'm Forest"},
    {"Sat 1 May", "15:00", "Coventry", "Man United"},
    {"Sat 1 May", "15:00", "Crystal Palace", "Aston Villa"},
    {"Sat 1 May", "15:00", "Fulham", "Everton"},
    {"Sat 1 May", "15:00", "Hull", "Bournemouth"},
    {"Sat 1 May", "15:00", "Ipswich", "Leeds"},
    {"Sat 1 May", "15:00", "Liverpool", "Chelsea"},
    {"Sat 1 May", "15:00", "Man City", "Brentford"},
    {"Sat 1 May", "15:00", "Sunderland", "Newcastle"},

    {"Sat 8 May", "15:00", "Bournemouth", "Man United"},
    {"Sat 8 May", "15:00", "Brentford", "Aston Villa"},
    {"Sat 8 May", "15:00", "Brighton", "Sunderland"},
    {"Sat 8 May", "15:00", "Everton", "Hull"},
    {"Sat 8 May", "15:00", "Fulham", "Ipswich"},
    {"Sat 8 May", "15:00", "Leeds", "Arsenal"},
    {"Sat 8 May", "15:00", "Man City", "Liverpool"},
    {"Sat 8 May", "15:00", "Newcastle", "Coventry"},
    {"Sat 8 May", "15:00", "Nott'm Forest", "Crystal Palace"},
    {"Sat 8 May", "15:00", "Tottenham", "Chelsea"},

    {"Sat 15 May", "15:00", "Arsenal", "Nott'm Forest"},
    {"Sat 15 May", "15:00", "Aston Villa", "Newcastle"},
    {"Sat 15 May", "15:00", "Chelsea", "Everton"},
    {"Sat 15 May", "15:00", "Coventry", "Tottenham"},
    {"Sat 15 May", "15:00", "Crystal Palace", "Brighton"},
    {"Sat 15 May", "15:00", "Hull", "Fulham"},
    {"Sat 15 May", "15:00", "Ipswich", "Man City"},
    {"Sat 15 May", "15:00", "Liverpool", "Brentford"},
    {"Sat 15 May", "15:00", "Man United", "Leeds"},
    {"Sat 15 May", "15:00", "Sunderland", "Bournemouth"},

    {"Sun 23 May", "15:00", "Bournemouth", "Chelsea"},
    {"Sun 23 May", "15:00", "Brentford", "Hull"},
    {"Sun 23 May", "15:00", "Brighton", "Liverpool"},
    {"Sun 23 May", "15:00", "Everton", "Arsenal"},
    {"Sun 23 May", "15:00", "Fulham", "Coventry"},
    {"Sun 23 May", "15:00", "Leeds", "Sunderland"},
    {"Sun 23 May", "15:00", "Man City", "Aston Villa"},
    {"Sun 23 May", "15:00", "Newcastle", "Crystal Palace"},
    {"Sun 23 May", "15:00", "Nott'm Forest", "Ipswich"},
    {"Sun 23 May", "15:00", "Tottenham", "Man United"},

    {"Sun 30 May", "16:00", "Arsenal", "Brighton"},
    {"Sun 30 May", "16:00", "Aston Villa", "Tottenham"},
    {"Sun 30 May", "16:00", "Chelsea", "Brentford"},
    {"Sun 30 May", "16:00", "Coventry", "Nott'm Forest"},
    {"Sun 30 May", "16:00", "Crystal Palace", "Leeds"},
    {"Sun 30 May", "16:00", "Hull", "Newcastle"},
    {"Sun 30 May", "16:00", "Ipswich", "Everton"},
    {"Sun 30 May", "16:00", "Liverpool", "Bournemouth"},
    {"Sun 30 May", "16:00", "Man United", "Fulham"},
    {"Sun 30 May", "16:00", "Sunderland", "Man City"}
};
#define N_REMAINING ((int)(sizeof(REMAINING) / sizeof(REMAINING[0])))

/* ============================================================
 * HELPERS
 * ============================================================ */
static int get_team_index(const char *name) {
    for (int i = 0; i < NUM_TEAMS; i++)
        if (strcmp(TEAMS[i], name) == 0) return i;
    return -1;
}

static const char *map_team_name(const char *csv_name) {
    for (int i = 0; NAME_MAP[i].csv_name != NULL; i++)
        if (strcmp(NAME_MAP[i].csv_name, csv_name) == 0)
            return NAME_MAP[i].script_name;
    return csv_name;
}

static double clamp(double v, double min, double max) {
    return v < min ? min : (v > max ? max : v);
}

static double rand_double(void) { return (double)rand() / (double)RAND_MAX; }

static void strip_quotes(char *s) {
    size_t len = strlen(s);
    if (len >= 2 && s[0] == '"' && s[len-1] == '"') {
        memmove(s, s + 1, len - 2);
        s[len - 2] = '\0';
    }
}

static int team_has_any_data(int i) {
    return current_stats[i].has_data || hist_stats[0][i].has_data || hist_stats[1][i].has_data;
}

/* Sort indices [0..n-1] by descending key[] */
static void sort_idx_desc(int *idx, int n, const double *key) {
    for (int i = 0; i < n - 1; i++) {
        int best = i;
        for (int j = i + 1; j < n; j++)
            if (key[idx[j]] > key[idx[best]]) best = j;
        int t = idx[i]; idx[i] = idx[best]; idx[best] = t;
    }
}

/* ============================================================
 * CSV PARSING - TEAM LEVEL
 * ============================================================ */
static void read_csv_into(const char *path, TeamStats *dest) {
    FILE *f = fopen(path, "r");
    if (!f) { printf("ERROR: Could not open %s\n", path); return; }

    char line[2048];
    int line_num = 0, teams_loaded = 0;

    while (fgets(line, sizeof(line), f)) {
        line_num++;
        if (line_num == 1) continue;

        line[strcspn(line, "\n\r")] = 0;
        if (strlen(line) == 0) continue;

        char *fields[30];
        int n_fields = 0;
        char *token = strtok(line, ";");

        while (token && n_fields < 30) {
            while (*token == ' ') token++;
            char *end = token + strlen(token) - 1;
            while (end > token && (*end == ' ' || *end == '\t')) *end-- = '\0';
            fields[n_fields++] = token;
            token = strtok(NULL, ";");
        }
        if (n_fields < 19) continue;

        char team_name[256];
        strncpy(team_name, fields[1], sizeof(team_name) - 1);
        team_name[sizeof(team_name) - 1] = '\0';
        strip_quotes(team_name);

        const char *script_name = map_team_name(team_name);
        int idx = get_team_index(script_name);
        if (idx < 0) continue;

        int matches = atoi(fields[2]);
        if (matches < 1) matches = 1;

        TeamStats *st = &dest[idx];
        st->has_data = 1;
        st->matches  = matches;
        st->wins     = atoi(fields[3]);
        st->draws    = atoi(fields[4]);
        st->loses    = atoi(fields[5]);
        st->goals    = atoi(fields[6]);
        st->ga       = atoi(fields[7]);
        st->points   = atoi(fields[8]);

        st->xG           = atof(fields[9])  / matches;
        st->NPxG         = atof(fields[10]) / matches;
        st->xGA          = atof(fields[11]) / matches;
        st->NPxGA        = atof(fields[12]) / matches;
        st->NPxGD        = atof(fields[13]) / matches;
        st->ppda         = atof(fields[14]);
        st->ppda_allowed = atof(fields[15]);
        st->deep         = atof(fields[16]) / matches;
        st->deep_allowed = atof(fields[17]) / matches;
        st->xPTS         = atof(fields[18]) / matches;

        teams_loaded++;
    }
    fclose(f);
    printf("  Loaded %d teams from %s\n", teams_loaded, path);
}

/* ============================================================
 * CSV PARSING - PLAYER LEVEL
 * ============================================================ */
static int split_player_fields(char *line, char *fields[], int max_fields) {
    int n = 0, in_quotes = 0;
    char *p = line, *start = line;

    while (*p && n < max_fields) {
        if (*p == '"') in_quotes = !in_quotes;
        else if (*p == ';' && !in_quotes) { *p = '\0'; fields[n++] = start; start = p + 1; }
        p++;
    }
    if (*start && n < max_fields) fields[n++] = start;

    for (int i = 0; i < n; i++) strip_quotes(fields[i]);
    return n;
}

static void read_player_csv_weighted(const char *path, double weight, int season_index) {
    FILE *f = fopen(path, "r");
    if (!f) { printf("  WARNING: could not open player CSV %s\n", path); return; }

    char line[2048];
    int line_num = 0, total_rows = 0, kept = 0, multi_team_count = 0, form_applied = 0;

    while (fgets(line, sizeof(line), f)) {
        line_num++;
        if (line_num == 1) continue;

        line[strcspn(line, "\n\r")] = 0;
        if (strlen(line) == 0) continue;
        total_rows++;

        char *fields[24];
        int n = split_player_fields(line, fields, 24);
        if (n < 20) continue;

        const char *player_name = fields[1];

        int mins = atoi(fields[4]);
        if (mins < PLAYER_MIN_MINS) continue;

        double xG90_raw = atof(fields[13]);
        double xA90_raw = atof(fields[15]);

        double xG90_c = xG90_raw > PLAYER_XG90_CAP ? PLAYER_XG90_CAP : xG90_raw;
        double xA90_c = xA90_raw > PLAYER_XA90_CAP ? PLAYER_XA90_CAP : xA90_raw;
        double comb   = xG90_c + xA90_c;

        /* Multi-team split */
        char team_buf[128];
        strncpy(team_buf, fields[2], sizeof(team_buf) - 1);
        team_buf[sizeof(team_buf) - 1] = '\0';

        char *team_tokens[8];
        int n_team_tokens = 0;
        char *tok = strtok(team_buf, ",");
        while (tok && n_team_tokens < 8) {
            while (*tok == ' ') tok++;
            char *end = tok + strlen(tok) - 1;
            while (end > tok && (*end == ' ' || *end == '\t')) *end-- = '\0';
            team_tokens[n_team_tokens++] = tok;
            tok = strtok(NULL, ",");
        }

        int team_indices[8], n_valid_teams = 0;
        for (int i = 0; i < n_team_tokens; i++) {
            const char *script_name = map_team_name(team_tokens[i]);
            int idx = get_team_index(script_name);
            if (idx >= 0) team_indices[n_valid_teams++] = idx;
        }
        if (n_valid_teams == 0) continue;
        if (n_valid_teams > 1) multi_team_count++;

        double split = 1.0 / (double)n_valid_teams;

        /* Form factor */
        double form_factor = 1.0;
        if (season_index == 0) {
            PlayerFormEntry *pf = find_player_form(player_name);
            if (pf && pf->has_2025 && pf->comb_2025 > 0.01 && comb > 0.01) {
                double ratio = comb / pf->comb_2025;
                if (ratio < FORM_MIN) ratio = FORM_MIN;
                if (ratio > FORM_MAX) ratio = FORM_MAX;
                form_factor = ratio;
                form_applied++;
            }
            PlayerFormEntry *pf2 = find_or_create_player_form(player_name);
            if (pf2) { pf2->comb_2026 += comb; pf2->has_2026 = 1; }
        } else {
            PlayerFormEntry *pf = find_or_create_player_form(player_name);
            if (pf) { pf->comb_2025 += comb; pf->has_2025 = 1; }
        }

        double eff_weight = weight * form_factor * split;

        for (int t = 0; t < n_valid_teams; t++) {
            int idx = team_indices[t];

            double xg = xG90_c * eff_weight;
            double xa = xA90_c * eff_weight;

            team_players[idx].sum_xG90     += xg;
            team_players[idx].sum_xA90     += xa;
            team_players[idx].sum_xG90xA90 += xg + xa;
            team_players[idx].n_players++;

            if (xg >= 0.10 * weight) team_players[idx].n_att++;

            if (xg > team_players[idx].top_xG90) {
                team_players[idx].top_xG90 = xg;
                strncpy(team_players[idx].top_scorer, player_name,
                        sizeof(team_players[idx].top_scorer) - 1);
                team_players[idx].top_scorer[sizeof(team_players[idx].top_scorer) - 1] = '\0';
            }
            if (xa > team_players[idx].top_xA90) {
                team_players[idx].top_xA90 = xa;
                strncpy(team_players[idx].top_creator, player_name,
                        sizeof(team_players[idx].top_creator) - 1);
                team_players[idx].top_creator[sizeof(team_players[idx].top_creator) - 1] = '\0';
            }

            team_players[idx].has_data = 1;
        }
        kept++;
    }
    fclose(f);

    printf("  %s: %d rows, %d kept (mins>=%d), %d multi-team, %d form-adj\n",
           path, total_rows, kept, PLAYER_MIN_MINS, multi_team_count, form_applied);
}

/* ============================================================
 * BLENDING & STRENGTHS
 * ============================================================ */
static void acc_season(double *acc, double *wsum, const TeamStats *st, double w) {
    if (!st->has_data) return;
    acc[0] += w * st->NPxG;         acc[1] += w * st->xG;
    acc[2] += w * st->NPxGA;        acc[3] += w * st->xGA;
    acc[4] += w * st->NPxGD;        acc[5] += w * st->deep;
    acc[6] += w * st->deep_allowed; acc[7] += w * st->xPTS;
    acc[8] += w * st->ppda;         acc[9] += w * st->ppda_allowed;
    *wsum += w;
}

static void compute_blended_and_strengths(void) {
    double league_mean[10] = {0};
    int count = 0;

    for (int i = 0; i < NUM_TEAMS; i++) {
        double wsum = 0.0, acc[10] = {0};
        acc_season(acc, &wsum, &current_stats[i],  SEASON_WEIGHT[0]);
        acc_season(acc, &wsum, &hist_stats[0][i],  SEASON_WEIGHT[1]);
        acc_season(acc, &wsum, &hist_stats[1][i],  SEASON_WEIGHT[2]);

        if (wsum > 0.0) {
            blended_stats[i].NPxG         = acc[0] / wsum;
            blended_stats[i].xG           = acc[1] / wsum;
            blended_stats[i].NPxGA        = acc[2] / wsum;
            blended_stats[i].xGA          = acc[3] / wsum;
            blended_stats[i].NPxGD        = acc[4] / wsum;
            blended_stats[i].deep         = acc[5] / wsum;
            blended_stats[i].deep_allowed = acc[6] / wsum;
            blended_stats[i].xPTS         = acc[7] / wsum;
            blended_stats[i].ppda         = acc[8] / wsum;
            blended_stats[i].ppda_allowed = acc[9] / wsum;
        }
    }

    for (int i = 0; i < NUM_TEAMS; i++) {
        if (team_has_any_data(i)) {
            league_mean[0] += blended_stats[i].NPxG;
            league_mean[1] += blended_stats[i].xG;
            league_mean[2] += blended_stats[i].NPxGA;
            league_mean[3] += blended_stats[i].xGA;
            league_mean[4] += blended_stats[i].NPxGD;
            league_mean[5] += blended_stats[i].deep;
            league_mean[6] += blended_stats[i].deep_allowed;
            league_mean[7] += blended_stats[i].xPTS;
            league_mean[8] += blended_stats[i].ppda;
            league_mean[9] += blended_stats[i].ppda_allowed;
            count++;
        }
    }
    if (count > 0) { for (int i = 0; i < 10; i++) league_mean[i] /= count; }
    else           { for (int i = 0; i < 10; i++) league_mean[i] = 1.0; }

    for (int i = 0; i < NUM_TEAMS; i++) {
        if (!team_has_any_data(i)) {
            blended_stats[i].NPxG         = league_mean[0];
            blended_stats[i].xG           = league_mean[1];
            blended_stats[i].NPxGA        = league_mean[2];
            blended_stats[i].xGA          = league_mean[3];
            blended_stats[i].NPxGD        = league_mean[4];
            blended_stats[i].deep         = league_mean[5];
            blended_stats[i].deep_allowed = league_mean[6];
            blended_stats[i].xPTS         = league_mean[7];
            blended_stats[i].ppda         = league_mean[8];
            blended_stats[i].ppda_allowed = league_mean[9];
        }
    }

    double means[10] = {0}, stds[10] = {0};
    for (int i = 0; i < NUM_TEAMS; i++) {
        means[0] += blended_stats[i].NPxG;
        means[1] += blended_stats[i].xG;
        means[2] += blended_stats[i].NPxGA;
        means[3] += blended_stats[i].xGA;
        means[4] += blended_stats[i].NPxGD;
        means[5] += blended_stats[i].deep;
        means[6] += blended_stats[i].deep_allowed;
        means[7] += blended_stats[i].xPTS;
        means[8] += blended_stats[i].ppda;
        means[9] += blended_stats[i].ppda_allowed;
    }
    for (int i = 0; i < 10; i++) means[i] /= NUM_TEAMS;

    for (int i = 0; i < NUM_TEAMS; i++) {
        stds[0] += pow(blended_stats[i].NPxG         - means[0], 2);
        stds[1] += pow(blended_stats[i].xG           - means[1], 2);
        stds[2] += pow(blended_stats[i].NPxGA        - means[2], 2);
        stds[3] += pow(blended_stats[i].xGA          - means[3], 2);
        stds[4] += pow(blended_stats[i].NPxGD        - means[4], 2);
        stds[5] += pow(blended_stats[i].deep         - means[5], 2);
        stds[6] += pow(blended_stats[i].deep_allowed - means[6], 2);
        stds[7] += pow(blended_stats[i].xPTS         - means[7], 2);
        stds[8] += pow(blended_stats[i].ppda         - means[8], 2);
        stds[9] += pow(blended_stats[i].ppda_allowed - means[9], 2);
    }
    for (int i = 0; i < 10; i++) stds[i] = sqrt(stds[i] / NUM_TEAMS) + 1e-9;

    /* ---------------------------------------------------------
     * Strengths
     * Attack uses 4 independent signals:
     *   - NPxG          (chance quality, primary)
     *   - deep          (territorial presence)
     *   - PPDA_allowed  (how much the opponent lets us press = how
     *                    dominant we are when we attack)
     *   - xPTS          (how many points our underlying play deserves)
     * Removed: xG (redundant with NPxG), NPxGD (already = NPxG - NPxGA)
     *
     * Defence uses 4 independent signals:
     *   - NPxGA         (chance quality conceded, primary)
     *   - deep_allowed  (territory conceded)
     *   - PPDA          (press intensity; lower = better)
     *   - xGA           (raw xG conceded, used as a quality check)
     * Removed: xPTS (already in attack), NPxGD (double-counted)
     * --------------------------------------------------------- */
    for (int i = 0; i < NUM_TEAMS; i++) {
        double z_npxg         = ( blended_stats[i].NPxG         - means[0]) / stds[0];
        double z_npxga        = (-blended_stats[i].NPxGA        + means[2]) / stds[2];
        double z_xga          = (-blended_stats[i].xGA          + means[3]) / stds[3];
        double z_deep         = ( blended_stats[i].deep         - means[5]) / stds[5];
        double z_deep_allowed = (-blended_stats[i].deep_allowed + means[6]) / stds[6];
        double z_xpts         = ( blended_stats[i].xPTS         - means[7]) / stds[7];
        double z_ppda         = (-blended_stats[i].ppda         + means[8]) / stds[8];
        double z_ppda_allowed = (-blended_stats[i].ppda_allowed + means[9]) / stds[9];

        double att_z = W_ATT_NPXG         * z_npxg
                     + W_ATT_DEEP         * z_deep
                     + W_ATT_PPDA_ALLOWED * z_ppda_allowed
                     + W_ATT_XPTS         * z_xpts;

        double def_z = W_DEF_NPXGA        * z_npxga
                     + W_DEF_DEEP_ALLOWED * z_deep_allowed
                     + W_DEF_PPDA         * z_ppda
                     + W_DEF_XGA          * z_xga;

        strengths[i].attack  = clamp(exp( ATTACK_SENS  * att_z), 0.70, 1.30);
        strengths[i].defence = clamp(exp(-DEFENCE_SENS * def_z), 0.70, 1.30);
    }
}

/* ============================================================
 * PLAYER ATTACK BLEND
 * ============================================================ */
static void apply_player_attack_blend(void) {
    double sum = 0.0, sum_sq = 0.0;
    int n = 0;

    for (int i = 0; i < NUM_TEAMS; i++) {
        if (!team_players[i].has_data) { player_att_z[i] = 0.0; continue; }
        double v = team_players[i].sum_xG90xA90;
        sum    += v;
        sum_sq += v * v;
        n++;
    }
    if (n < 2) {
        for (int i = 0; i < NUM_TEAMS; i++) player_att_z[i] = 0.0;
        return;
    }

    double mean = sum / n;
    double var  = sum_sq / n - mean * mean;
    double std  = sqrt(var > 1e-9 ? var : 1e-9);

    for (int i = 0; i < NUM_TEAMS; i++) {
        if (!team_players[i].has_data) { player_att_z[i] = 0.0; continue; }

        player_att_z[i] = (team_players[i].sum_xG90xA90 - mean) / std;

        team_players[i].star_share = (team_players[i].sum_xG90 > 0.01)
            ? team_players[i].top_xG90 / team_players[i].sum_xG90 : 0.0;

        double blend = exp(PLAYER_ATT_WEIGHT * player_att_z[i]);
        strengths[i].attack = clamp(strengths[i].attack * blend, 0.70, 1.30);
    }
}

/* ============================================================
 * ELO NORMALISATION
 * ============================================================ */
static void compute_elo_ratings(void) {
    double def_qual[NUM_TEAMS];
    double sum_att = 0.0, sum_defq = 0.0;

    for (int i = 0; i < NUM_TEAMS; i++) {
        def_qual[i] = 1.0 / strengths[i].defence;
        sum_att  += strengths[i].attack;
        sum_defq += def_qual[i];
    }

    double scale_att = ELO_HALF / sum_att;
    double scale_def = ELO_HALF / sum_defq;

    double sum_att_c = 0.0, sum_def_c = 0.0;
    for (int i = 0; i < NUM_TEAMS; i++) {
        double a_lin = strengths[i].attack * scale_att;
        double d_lin = def_qual[i]         * scale_def;

        elo_attack[i]  = ELO_PER_SIDE + (a_lin - ELO_PER_SIDE) * ELO_COMPRESS;
        elo_defence[i] = ELO_PER_SIDE + (d_lin - ELO_PER_SIDE) * ELO_COMPRESS;
        sum_att_c += elo_attack[i];
        sum_def_c += elo_defence[i];
    }

    double renorm_att = ELO_HALF / sum_att_c;
    double renorm_def = ELO_HALF / sum_def_c;
    for (int i = 0; i < NUM_TEAMS; i++) {
        elo_attack[i]  *= renorm_att;
        elo_defence[i] *= renorm_def;
        elo_combined[i] = elo_attack[i] + elo_defence[i];
    }
}

/* ============================================================
 * BUILD STATE & FIXTURES
 * ============================================================ */
static void reset_h2h(void) {
    memset(h2h_points, 0, sizeof(h2h_points));
    memset(h2h_gf, 0, sizeof(h2h_gf));
    memset(h2h_ga, 0, sizeof(h2h_ga));
}

static void build_current_from_completed(void) {
    reset_h2h();

    for (int i = 0; i < N_COMPLETED; i++) {
        int h = get_team_index(COMPLETED[i].h);
        int a = get_team_index(COMPLETED[i].a);
        if (h < 0 || a < 0) continue;

        cur_gf[h] += COMPLETED[i].hg;  cur_ga[h] += COMPLETED[i].ag;
        cur_gf[a] += COMPLETED[i].ag;  cur_ga[a] += COMPLETED[i].hg;

        cur_pts[h] += (COMPLETED[i].hg > COMPLETED[i].ag) ? 3 :
                      (COMPLETED[i].hg == COMPLETED[i].ag ? 1 : 0);
        cur_pts[a] += (COMPLETED[i].ag > COMPLETED[i].hg) ? 3 :
                      (COMPLETED[i].hg == COMPLETED[i].ag ? 1 : 0);

        if      (COMPLETED[i].hg > COMPLETED[i].ag) { cur_w[h]++; cur_l[a]++; }
        else if (COMPLETED[i].ag > COMPLETED[i].hg) { cur_w[a]++; cur_l[h]++; }
        else                                        { cur_d[h]++; cur_d[a]++; }

        /* Track head-to-head */
        if (COMPLETED[i].hg > COMPLETED[i].ag) {
            h2h_points[h][a] += 3;
        } else if (COMPLETED[i].hg == COMPLETED[i].ag) {
            h2h_points[h][a] += 1;
            h2h_points[a][h] += 1;
        } else {
            h2h_points[a][h] += 3;
        }
        h2h_gf[h][a] += COMPLETED[i].hg;
        h2h_ga[h][a] += COMPLETED[i].ag;
        h2h_gf[a][h] += COMPLETED[i].ag;
        h2h_ga[a][h] += COMPLETED[i].hg;
    }
    for (int i = 0; i < NUM_TEAMS; i++) cur_gd[i] = cur_gf[i] - cur_ga[i];
}

static void build_remaining_from_schedule(double base_home_xg, double base_away_xg) {
    for (int i = 0; i < N_REMAINING; i++) {
        int h = get_team_index(REMAINING[i].home);
        int a = get_team_index(REMAINING[i].away);
        if (h < 0 || a < 0) {
            printf("  Unknown team in schedule: %s vs %s\n", REMAINING[i].home, REMAINING[i].away);
            continue;
        }

        Fixture *fx = &remaining_fixtures[n_remaining];
        fx->h_idx = h;
        fx->a_idx = a;

        strncpy(fx->date, REMAINING[i].date, sizeof(fx->date) - 1); fx->date[sizeof(fx->date) - 1] = '\0';
        strncpy(fx->time, REMAINING[i].time, sizeof(fx->time) - 1); fx->time[sizeof(fx->time) - 1] = '\0';

        /* Attack vs Defence */
        double att_h = elo_attack[h]  / ELO_PER_SIDE;   /* ~1.0 average */
        double def_h = elo_defence[h] / ELO_PER_SIDE;
        double att_a = elo_attack[a]  / ELO_PER_SIDE;
        double def_a = elo_defence[a] / ELO_PER_SIDE;

        double lam_h = base_home_xg * att_h / def_a;
        double lam_a = base_away_xg * att_a / def_h;

        /* Combined Elo (attack + defence) tilts the split */
        double E_h = 1.0 / (1.0 + pow(10.0, (elo_combined[a] - elo_combined[h]) / ELO_SCALE));
        double total = lam_h + lam_a;
        double share_h = clamp(0.5 + (E_h - 0.5) * ELO_SHARE_K, 0.15, 0.85);

        lam_h = total * share_h;
        lam_a = total * (1.0 - share_h);

        lam_h = clamp(lam_h, 0.05, 6.0);
        lam_a = clamp(lam_a, 0.05, 6.0);

        fx->lam_h = lam_h;
        fx->lam_a = lam_a;

        double p_h = exp(-lam_h), p_a = exp(-lam_a);
        double cum_h = 0, cum_a = 0;
        for (int k = 0; k <= MAX_GOALS; k++) {
            cum_h += p_h; fx->cum_h[k] = cum_h;
            cum_a += p_a; fx->cum_a[k] = cum_a;
            p_h *= lam_h / (k + 1);
            p_a *= lam_a / (k + 1);
        }
        for (int k = 0; k <= MAX_GOALS; k++) {
            fx->cum_h[k] /= cum_h;
            fx->cum_a[k] /= cum_a;
        }
        n_remaining++;
    }
}

/* ============================================================
 * PREMIER LEAGUE TIE-BREAKER LOGIC
 * ============================================================ */
typedef struct {
    int team_idx;
    int pts;
    int gf;
    int ga;
    int gd;
} TeamRankInfo;

/* Compare two teams using Premier League tie-breaker rules.
 * Returns negative if team_a should rank higher, positive if team_b should rank higher. */
static int compare_teams_tiebreaker(int team_a, int team_b,
                                    const int *sim_pts, const int *sim_gf, const int *sim_ga,
                                    const int sim_h2h_points[][NUM_TEAMS],
                                    const int sim_h2h_gf[][NUM_TEAMS]) {
    /* 1. Points */
    if (sim_pts[team_a] != sim_pts[team_b])
        return sim_pts[team_b] - sim_pts[team_a];

    /* 2. Goal Difference */
    int gd_a = sim_gf[team_a] - sim_ga[team_a];
    int gd_b = sim_gf[team_b] - sim_ga[team_b];
    if (gd_a != gd_b)
        return gd_b - gd_a;

    /* 3. Goals Scored */
    if (sim_gf[team_a] != sim_gf[team_b])
        return sim_gf[team_b] - sim_gf[team_a];

    /* 4. Head-to-Head Points */
    int h2h_pts_a = sim_h2h_points[team_a][team_b];
    int h2h_pts_b = sim_h2h_points[team_b][team_a];
    if (h2h_pts_a != h2h_pts_b)
        return h2h_pts_b - h2h_pts_a;

    /* 5. Head-to-Head Away Goals */
    int h2h_away_a = sim_h2h_gf[team_a][team_b];
    int h2h_away_b = sim_h2h_gf[team_b][team_a];
    if (h2h_away_a != h2h_away_b)
        return h2h_away_b - h2h_away_a;

    /* 6. Play-off (random tie-breaker for simulation purposes) */
    double r = rand_double();
    return (r < 0.5) ? -1 : 1;
}

static int team_rank_comparator(const void *a, const void *b) {
    const TeamRankInfo *ta = (const TeamRankInfo *)a;
    const TeamRankInfo *tb = (const TeamRankInfo *)b;

    if (tb->pts != ta->pts) return tb->pts - ta->pts;
    if (tb->gd != ta->gd) return tb->gd - ta->gd;
    if (tb->gf != ta->gf) return tb->gf - ta->gf;
    return 0;
}

static void run_simulations(void) {
    printf("Running %d simulations...\n", N_SIMS);
    int last_pct = -1;

    for (int sim = 0; sim < N_SIMS; sim++) {
        int pct = (sim * 100) / N_SIMS;
        if (pct != last_pct && pct % 5 == 0) {
            char bar[22];
            int filled = pct / 5;
            for (int i = 0; i < 20; i++)
                bar[i] = (i < filled) ? '=' : (i == filled ? '>' : ' ');
            bar[20] = '\0';
            printf("\r  Progress: [%-20s] %3d%%", bar, pct);
            fflush(stdout);
            last_pct = pct;
        }

        int sim_pts[NUM_TEAMS], sim_gf[NUM_TEAMS], sim_ga[NUM_TEAMS];
        int sim_w[NUM_TEAMS], sim_d[NUM_TEAMS], sim_l[NUM_TEAMS];
        int sim_h2h_points[NUM_TEAMS][NUM_TEAMS];
        int sim_h2h_gf[NUM_TEAMS][NUM_TEAMS];

        for (int i = 0; i < NUM_TEAMS; i++) {
            sim_pts[i] = cur_pts[i]; sim_gf[i] = cur_gf[i]; sim_ga[i] = cur_ga[i];
            sim_w[i]   = cur_w[i];   sim_d[i]  = cur_d[i];  sim_l[i]  = cur_l[i];
        }

        memcpy(sim_h2h_points, h2h_points, sizeof(h2h_points));
        memcpy(sim_h2h_gf, h2h_gf, sizeof(h2h_gf));

        for (int f = 0; f < n_remaining; f++) {
            int h = remaining_fixtures[f].h_idx;
            int a = remaining_fixtures[f].a_idx;

            double u_h = rand_double(), u_a = rand_double();
            int goals_h = 0, goals_a = 0;
            while (goals_h < MAX_GOALS && u_h > remaining_fixtures[f].cum_h[goals_h]) goals_h++;
            while (goals_a < MAX_GOALS && u_a > remaining_fixtures[f].cum_a[goals_a]) goals_a++;

            sim_gf[h] += goals_h; sim_ga[h] += goals_a;
            sim_gf[a] += goals_a; sim_ga[a] += goals_h;

            if      (goals_h > goals_a) {
                sim_pts[h] += 3; sim_w[h]++; sim_l[a]++;
                sim_h2h_points[h][a] += 3;
            }
            else if (goals_a > goals_h) {
                sim_pts[a] += 3; sim_w[a]++; sim_l[h]++;
                sim_h2h_points[a][h] += 3;
            }
            else {
                sim_pts[h]++; sim_pts[a]++; sim_d[h]++; sim_d[a]++;
                sim_h2h_points[h][a] += 1;
                sim_h2h_points[a][h] += 1;
            }

            sim_h2h_gf[h][a] += goals_h;
            sim_h2h_gf[a][h] += goals_a;
        }

        TeamRankInfo rank_info[NUM_TEAMS];
        int order[NUM_TEAMS];

        for (int i = 0; i < NUM_TEAMS; i++) {
            rank_info[i].team_idx = i;
            rank_info[i].pts = sim_pts[i];
            rank_info[i].gf = sim_gf[i];
            rank_info[i].ga = sim_ga[i];
            rank_info[i].gd = sim_gf[i] - sim_ga[i];
            order[i] = i;
        }

        qsort(rank_info, NUM_TEAMS, sizeof(TeamRankInfo), team_rank_comparator);

        /* Bubble pass for full tie-breakers (stable within equal groups) */
        for (int i = 0; i < NUM_TEAMS - 1; i++) {
            for (int j = 0; j < NUM_TEAMS - 1 - i; j++) {
                int team_a = rank_info[j].team_idx;
                int team_b = rank_info[j+1].team_idx;

                int cmp = compare_teams_tiebreaker(team_a, team_b,
                                                   sim_pts, sim_gf, sim_ga,
                                                   sim_h2h_points, sim_h2h_gf);

                if (cmp > 0) {
                    TeamRankInfo temp = rank_info[j];
                    rank_info[j] = rank_info[j+1];
                    rank_info[j+1] = temp;
                }
            }
        }

        for (int i = 0; i < NUM_TEAMS; i++) {
            order[i] = rank_info[i].team_idx;
        }

        title_c[order[0]]++;
        top4_c[order[0]]++; top4_c[order[1]]++; top4_c[order[2]]++; top4_c[order[3]]++;
        fifth_c[order[4]]++;
        top6_c[order[0]]++; top6_c[order[1]]++; top6_c[order[2]]++;
        top6_c[order[3]]++; top6_c[order[4]]++; top6_c[order[5]]++;
        rel_c[order[17]]++; rel_c[order[18]]++; rel_c[order[19]]++;

        for (int i = 0; i < NUM_TEAMS; i++) {
            pts_sum[i] += sim_pts[i];
            gf_sum[i]  += sim_gf[i];
            ga_sum[i]  += sim_ga[i];
            win_c[i]   += sim_w[i] - cur_w[i];
            draw_c[i]  += sim_d[i] - cur_d[i];
            loss_c[i]  += sim_l[i] - cur_l[i];
        }
        for (int p = 0; p < NUM_TEAMS; p++) {
            pos_sum[order[p]] += (p + 1);
        }
        sims_done++;
    }
    printf("\r  Progress: [====================] 100%%\n");
}

/* ============================================================
 * OUTPUT
 * ============================================================ */
static void print_elo_table(void) {
    printf("\n================================================================================\n");
    printf("  ELO RATINGS  (Combined = Attack + Defence)\n");
    printf("================================================================================\n");
    printf("  %-18s  %12s  %12s  %12s\n",
           "TEAM", "ATTACK", "DEFENCE", "COMBINED");
    printf("  ------------------------------------------------------------------------------\n");

    int order[NUM_TEAMS];
    for (int i = 0; i < NUM_TEAMS; i++) order[i] = i;
    sort_idx_desc(order, NUM_TEAMS, elo_combined);

    double sum_a = 0, sum_d = 0, sum_c = 0;
    for (int r = 0; r < NUM_TEAMS; r++) {
        int i = order[r];
        printf("  %-18s  %12.2f  %12.2f  %12.2f\n",
               TEAMS[i], elo_attack[i], elo_defence[i], elo_combined[i]);
        sum_a += elo_attack[i];
        sum_d += elo_defence[i];
        sum_c += elo_combined[i];
    }
    printf("  ------------------------------------------------------------------------------\n");
    printf("  %-18s  %12.2f  %12.2f  %12.2f\n", "TOTALS", sum_a, sum_d, sum_c);
    printf("================================================================================\n");
}

static void print_and_save_results(void) {
    int order[NUM_TEAMS];
    for (int i = 0; i < NUM_TEAMS; i++) order[i] = i;
    sort_idx_desc(order, NUM_TEAMS, pts_sum);

    printf("\n================================================================================\n");
    printf("  FINAL PROJECTION (%d simulations)\n", N_SIMS);
    printf("================================================================================\n");
    printf("  %-2s  %-18s  %7s  %7s  %7s  %7s  %7s  %7s\n",
           "#", "TEAM", "AVG PTS", "TITLE%", "TOP4%", "EURO%", "5TH%", "REL%");
    printf("  ------------------------------------------------------------------------------\n");

    FILE *csv = fopen("final_probabilities.csv", "w");
    if (csv) {
        fprintf(csv, "Rank,Team,CurrentPoints,AvgFinalPoints,AvgPosition,AvgW,AvgD,AvgL,AvgGF,AvgGA,AvgGD,TitlePct,Top4Pct,EuroPct,FifthPct,Top6Pct,RelegationPct,BlendedNPxG,BlendedNPxGA,BlendedNPxGD,BlendedxPTS,BlendedPPDA,BlendedPPDAAllowed,PlayerSumXG90,PlayerSumXA90,StarShare,TopScorer,AttackElo,DefenceElo,CombinedElo\n");
    }

    for (int r = 0; r < NUM_TEAMS; r++) {
        int i = order[r];
        double avg_pts = pts_sum[i] / sims_done;
        double avg_pos = pos_sum[i] / sims_done;
        double avg_w   = cur_w[i]  + (double)win_c[i]  / sims_done;
        double avg_d   = cur_d[i]  + (double)draw_c[i] / sims_done;
        double avg_l   = cur_l[i]  + (double)loss_c[i] / sims_done;
        double avg_gf  = gf_sum[i] / sims_done;
        double avg_ga  = ga_sum[i] / sims_done;
        double avg_gd  = avg_gf - avg_ga;

        printf("  %-2d  %-18s  %7.2f  %7.2f  %7.2f  %7.2f  %7.2f  %7.2f\n",
               r + 1, TEAMS[i], avg_pts,
               (double)title_c[i] / sims_done * 100.0,
               (double)top4_c[i]  / sims_done * 100.0,
               (double)(top4_c[i] + fifth_c[i]) / sims_done * 100.0,
               (double)fifth_c[i] / sims_done * 100.0,
               (double)rel_c[i]   / sims_done * 100.0);

        if (csv) {
            fprintf(csv, "%d,%s,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.4f,%s,%.2f,%.2f,%.2f\n",
                    r + 1, TEAMS[i], cur_pts[i], avg_pts, avg_pos, avg_w, avg_d, avg_l,
                    avg_gf, avg_ga, avg_gd,
                    (double)title_c[i] / sims_done * 100.0,
                    (double)top4_c[i]  / sims_done * 100.0,
                    (double)(top4_c[i] + fifth_c[i]) / sims_done * 100.0,
                    (double)fifth_c[i] / sims_done * 100.0,
                    (double)top6_c[i]  / sims_done * 100.0,
                    (double)rel_c[i]   / sims_done * 100.0,
                    blended_stats[i].NPxG, blended_stats[i].NPxGA, blended_stats[i].NPxGD,
                    blended_stats[i].xPTS, blended_stats[i].ppda, blended_stats[i].ppda_allowed,
                    team_players[i].sum_xG90, team_players[i].sum_xA90,
                    team_players[i].star_share,
                    team_players[i].top_scorer[0] ? team_players[i].top_scorer : "-",
                    elo_attack[i], elo_defence[i], elo_combined[i]);
        }
    }
    printf("================================================================================\n");
    if (csv) {
        fclose(csv);
        printf("  CSV saved -> final_probabilities.csv\n");
    }
}

/* ============================================================
 * MAIN
 * ============================================================ */
int main(int argc, char **argv) {
#ifdef _WIN32
    SetConsoleOutputCP(65001);
#endif

    srand((unsigned)time(NULL));

    const char *current_csv     = "C:\\Users\\liam\\Documents\\GitHub\\all-of-my-code\\APPS\\league-chemp.csv";
    const char *hist_2025_csv   = "C:\\Users\\liam\\Documents\\GitHub\\all-of-my-code\\APPS\\league-chemp-2025.csv";
    const char *hist_2024_csv   = "C:\\Users\\liam\\Documents\\GitHub\\all-of-my-code\\APPS\\league-chemp-2024.csv";
    const char *player_2026_csv = "C:\\Users\\liam\\Documents\\GitHub\\all-of-my-code\\APPS\\players2026.csv";
    const char *player_2025_csv = "C:\\Users\\liam\\Documents\\GitHub\\all-of-my-code\\APPS\\players2025.csv";

    if (argc >= 2) current_csv     = argv[1];
    if (argc >= 3) hist_2025_csv   = argv[2];
    if (argc >= 4) hist_2024_csv   = argv[3];
    if (argc >= 5) player_2026_csv = argv[4];
    if (argc >= 6) player_2025_csv = argv[5];

    printf("================================================================================\n");
    printf("  Premier League 2026/27 Monte Carlo Simulator\n");
    printf("  Time-decay history + multi-team split + player form + combined Elo\n");
    printf("================================================================================\n");

    read_csv_into(current_csv,   current_stats);
    read_csv_into(hist_2025_csv, hist_stats[0]);
    read_csv_into(hist_2024_csv, hist_stats[1]);

    read_player_csv_weighted(player_2025_csv, SEASON_WEIGHT[1], 1);
    read_player_csv_weighted(player_2026_csv, SEASON_WEIGHT[0], 0);

    compute_blended_and_strengths();
    apply_player_attack_blend();
    compute_elo_ratings();

    double base_xg_per_team = 0.0;
    for (int i = 0; i < NUM_TEAMS; i++) base_xg_per_team += blended_stats[i].xG;
    base_xg_per_team /= NUM_TEAMS;

    double base_home_xg = base_xg_per_team * 1.118;
    double base_away_xg = base_xg_per_team * 0.882;

    build_current_from_completed();
    build_remaining_from_schedule(base_home_xg, base_away_xg);

    printf("  Completed: %d | Remaining: %d | Total: %d | Sims: %d\n",
           N_COMPLETED, n_remaining, N_COMPLETED + n_remaining, N_SIMS);

    print_elo_table();

    run_simulations();
    print_and_save_results();

    return 0;
}