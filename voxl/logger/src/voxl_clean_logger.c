/*
 * voxl-clean-logger (B2)
 *
 * Subscribes to MPA pipes for IMU and GPS data and writes one CSV per
 * stream with a stable, decoded schema. Intended to run on the VOXL 2
 * companion compute (Starling 2). Build with the provided Makefile,
 * which links against libmodal_pipe and the system MAVLink C headers.
 *
 * Output (under <out_dir>/, default /data/voxl-clean-logger/<YYYYmmdd_HHMMSS>):
 *   imu_apps/data.csv
 *   imu_px4/data.csv
 *   gps/data.csv
 *
 * Schemas match host/parse_logs.py expectations.
 */

#include <c_library_v2/common/mavlink.h>
#include <errno.h>
#include <getopt.h>
#include <modal_pipe_client.h>
#include <modal_pipe_interfaces.h>
#include <modal_start_stop.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define CLIENT_NAME "voxl-clean-logger"

#define CH_IMU_APPS 0
#define CH_IMU_PX4  1
#define CH_GPS      2

static const char *DEFAULT_BASE_DIR = "/data/voxl-clean-logger";
static const char *PIPE_IMU_APPS = "imu_apps";
static const char *PIPE_IMU_PX4  = "imu_px4";
static const char *PIPE_GPS      = "mavlink_gps_raw_int";

static FILE *fd_imu_apps = NULL;
static FILE *fd_imu_px4  = NULL;
static FILE *fd_gps      = NULL;

static int mkdir_p(const char *path) {
    char buf[512];
    snprintf(buf, sizeof(buf), "%s", path);
    for (char *p = buf + 1; *p; p++) {
        if (*p == '/') {
            *p = 0;
            if (mkdir(buf, 0755) && errno != EEXIST) return -1;
            *p = '/';
        }
    }
    if (mkdir(buf, 0755) && errno != EEXIST) return -1;
    return 0;
}

static FILE *open_csv(const char *flight_dir, const char *stream, const char *header) {
    char dir[512], path[600];
    snprintf(dir,  sizeof(dir),  "%s/%s", flight_dir, stream);
    snprintf(path, sizeof(path), "%s/data.csv", dir);
    if (mkdir_p(dir) != 0) { perror("mkdir"); return NULL; }
    FILE *f = fopen(path, "w");
    if (!f) { perror("fopen"); return NULL; }
    fputs(header, f);
    return f;
}

static void imu_cb(int ch, char *data, int bytes, __attribute__((unused)) void *ctx) {
    if (bytes <= 0) return;
    int n = 0;
    imu_data_t *arr = pipe_validate_imu_data_t(data, bytes, &n);
    if (!arr) return;
    FILE *f = (ch == CH_IMU_APPS) ? fd_imu_apps : fd_imu_px4;
    if (!f) return;
    for (int i = 0; i < n; i++) {
        fprintf(f, "%lu,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f\n",
                (unsigned long)arr[i].timestamp_ns,
                arr[i].accl_ms2[0], arr[i].accl_ms2[1], arr[i].accl_ms2[2],
                arr[i].gyro_rad[0], arr[i].gyro_rad[1], arr[i].gyro_rad[2],
                arr[i].temp_c);
    }
}

static void gps_cb(__attribute__((unused)) int ch, char *data, int bytes,
                   __attribute__((unused)) void *ctx) {
    if (bytes <= 0 || !fd_gps) return;
    int n = 0;
    mavlink_message_t *msgs = pipe_validate_mavlink_message_t(data, bytes, &n);
    if (!msgs) return;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    uint64_t now_ns = (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
    for (int i = 0; i < n; i++) {
        if (msgs[i].msgid != MAVLINK_MSG_ID_GPS_RAW_INT) continue;
        mavlink_gps_raw_int_t g;
        mavlink_msg_gps_raw_int_decode(&msgs[i], &g);
        fprintf(fd_gps, "%lu,%lu,%u,%.7f,%.7f,%.3f,%.3f,%.3f,%.3f,%.2f,%u\n",
                (unsigned long)now_ns,
                (unsigned long)g.time_usec,
                (unsigned)g.fix_type,
                g.lat / 1e7, g.lon / 1e7, g.alt / 1000.0,
                g.eph / 100.0, g.epv / 100.0,
                g.vel / 100.0, g.cog / 100.0,
                (unsigned)g.satellites_visible);
    }
}

static void on_disconnect(int ch, __attribute__((unused)) void *ctx) {
    fprintf(stderr, "disconnected from ch %d\n", ch);
}

int main(int argc, char **argv) {
    const char *base_dir = DEFAULT_BASE_DIR;
    int opt;
    while ((opt = getopt(argc, argv, "d:h")) != -1) {
        if (opt == 'd') base_dir = optarg;
        else { printf("usage: %s [-d base_dir]\n", argv[0]); return 0; }
    }

    enable_signal_handler();
    main_running = 1;

    char flight_dir[512];
    time_t t = time(NULL); struct tm tm = *localtime(&t);
    snprintf(flight_dir, sizeof(flight_dir), "%s/%04d%02d%02d_%02d%02d%02d",
             base_dir, tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
             tm.tm_hour, tm.tm_min, tm.tm_sec);
    if (mkdir_p(flight_dir) != 0) return 1;
    printf("logging to %s\n", flight_dir);

    const char *imu_hdr = "timestamp_ns,ax_ms2,ay_ms2,az_ms2,gx_rads,gy_rads,gz_rads,temp_c\n";
    const char *gps_hdr = "timestamp_ns,time_usec,fix_type,lat_deg,lon_deg,alt_m,"
                          "eph_m,epv_m,vel_ms,cog_deg,satellites_visible\n";
    fd_imu_apps = open_csv(flight_dir, "imu_apps", imu_hdr);
    fd_imu_px4  = open_csv(flight_dir, "imu_px4",  imu_hdr);
    fd_gps      = open_csv(flight_dir, "gps",      gps_hdr);
    if (!fd_imu_apps || !fd_imu_px4 || !fd_gps) return 1;

    pipe_client_set_simple_helper_cb(CH_IMU_APPS, imu_cb, NULL);
    pipe_client_set_disconnect_cb(CH_IMU_APPS, on_disconnect, NULL);
    pipe_client_open(CH_IMU_APPS, PIPE_IMU_APPS, CLIENT_NAME,
                     EN_PIPE_CLIENT_SIMPLE_HELPER, IMU_RECOMMENDED_READ_BUF_SIZE);

    pipe_client_set_simple_helper_cb(CH_IMU_PX4, imu_cb, NULL);
    pipe_client_set_disconnect_cb(CH_IMU_PX4, on_disconnect, NULL);
    pipe_client_open(CH_IMU_PX4, PIPE_IMU_PX4, CLIENT_NAME,
                     EN_PIPE_CLIENT_SIMPLE_HELPER, IMU_RECOMMENDED_READ_BUF_SIZE);

    pipe_client_set_simple_helper_cb(CH_GPS, gps_cb, NULL);
    pipe_client_set_disconnect_cb(CH_GPS, on_disconnect, NULL);
    pipe_client_open(CH_GPS, PIPE_GPS, CLIENT_NAME,
                     EN_PIPE_CLIENT_SIMPLE_HELPER,
                     MAVLINK_MESSAGE_T_RECOMMENDED_READ_BUF_SIZE);

    while (main_running) usleep(200000);

    pipe_client_close_all();
    if (fd_imu_apps) fclose(fd_imu_apps);
    if (fd_imu_px4)  fclose(fd_imu_px4);
    if (fd_gps)      fclose(fd_gps);
    printf("done.\n");
    return 0;
}
