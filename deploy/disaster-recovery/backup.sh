#!/bin/bash
# 跨区域备份脚本
# 用途：将数据库和配置备份到多个区域

set -e

# 配置变量
PRIMARY_REGION="asia-east1"
BACKUP_REGIONS=("asia-northeast1" "us-west1")
PROJECT_ID="lianghua-project"
DB_INSTANCE="lianghua-db-primary"
BACKUP_BUCKET="lianghua-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# 错误处理
error_exit() {
    log "ERROR: $1"
    exit 1
}

# 创建数据库备份
create_database_backup() {
    log "Creating database backup..."

    # PostgreSQL备份
    pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME -F c -f "/tmp/lianghua_db_${TIMESTAMP}.dump"

    # 压缩备份
    gzip "/tmp/lianghua_db_${TIMESTAMP}.dump"

    log "Database backup created: lianghua_db_${TIMESTAMP}.dump.gz"
}

# 备份Redis数据
backup_redis() {
    log "Creating Redis backup..."

    # 触发Redis RDB快照
    redis-cli -h $REDIS_HOST BGSAVE

    # 等待快照完成
    sleep 10

    # 复制RDB文件
    gsutil cp gs://${BACKUP_BUCKET}/redis/dump.rdb gs://${BACKUP_BUCKET}/redis/dump_${TIMESTAMP}.rdb

    log "Redis backup completed"
}

# 备份应用配置
backup_configs() {
    log "Backing up application configurations..."

    # Kubernetes secrets（加密后）
    kubectl get secrets -n lianghua -o yaml > /tmp/secrets_${TIMESTAMP}.yaml

    # Kubernetes configmaps
    kubectl get configmaps -n lianghua -o yaml > /tmp/configmaps_${TIMESTAMP}.yaml

    # Helm values
    cp deploy/kubernetes/values*.yaml /tmp/

    # 打包配置
    tar -czf /tmp/configs_${TIMESTAMP}.tar.gz -C /tmp \
        secrets_${TIMESTAMP}.yaml \
        configmaps_${TIMESTAMP}.yaml \
        values*.yaml

    log "Configuration backup completed"
}

# 上传到主区域
upload_to_primary() {
    log "Uploading backups to primary region..."

    gsutil cp /tmp/lianghua_db_${TIMESTAMP}.dump.gz \
        gs://${BACKUP_BUCKET}/${PRIMARY_REGION}/database/

    gsutil cp /tmp/configs_${TIMESTAMP}.tar.gz \
        gs://${BACKUP_BUCKET}/${PRIMARY_REGION}/configs/

    log "Upload to primary region completed"
}

# 复制到备份区域
replicate_to_backup_regions() {
    log "Replicating to backup regions..."

    for region in "${BACKUP_REGIONS[@]}"; do
        log "Replicating to $region..."

        # 使用gsutil跨区域复制
        gsutil -m rsync -r \
            gs://${BACKUP_BUCKET}/${PRIMARY_REGION}/ \
            gs://${BACKUP_BUCKET}/${region}/

        log "Replication to $region completed"
    done
}

# 验证备份完整性
verify_backups() {
    log "Verifying backup integrity..."

    # 验证数据库备份
    local db_backup="/tmp/lianghua_db_${TIMESTAMP}.dump.gz"
    if [ -f "$db_backup" ]; then
        local size=$(stat -f%z "$db_backup" 2>/dev/null || stat -c%s "$db_backup")
        if [ "$size" -lt 1000 ]; then
            error_exit "Database backup file too small: $size bytes"
        fi
        log "Database backup verified: $size bytes"
    else
        error_exit "Database backup file not found"
    fi

    # 验证配置备份
    local config_backup="/tmp/configs_${TIMESTAMP}.tar.gz"
    if [ -f "$config_backup" ]; then
        log "Configuration backup verified"
    else
        error_exit "Configuration backup file not found"
    fi
}

# 清理旧备份（保留30天）
cleanup_old_backups() {
    log "Cleaning up old backups..."

    # 删除30天前的备份
    gsutil -m rm -a gs://${BACKUP_BUCKET}/**/database/lianghua_db_$(date -d '-30 days' +%Y%m%d)*.dump.gz || true

    log "Cleanup completed"
}

# 发送通知
send_notification() {
    local status=$1
    local message=$2

    # Slack通知
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"Lianghua Backup ${status}: ${message}\"}" \
        $SLACK_WEBHOOK_URL || true

    # 邮件通知
    echo "$message" | mail -s "Lianghua Backup ${status}" $NOTIFICATION_EMAIL || true
}

# 主函数
main() {
    log "Starting backup process..."

    send_notification "Started" "Backup process started at ${TIMESTAMP}"

    # 执行备份步骤
    create_database_backup || error_exit "Database backup failed"
    backup_redis || error_exit "Redis backup failed"
    backup_configs || error_exit "Configuration backup failed"

    # 验证
    verify_backups || error_exit "Backup verification failed"

    # 上传
    upload_to_primary || error_exit "Upload to primary region failed"
    replicate_to_backup_regions || error_exit "Replication to backup regions failed"

    # 清理
    cleanup_old_backups

    log "Backup process completed successfully"
    send_notification "Completed" "Backup completed successfully at ${TIMESTAMP}"
}

# 运行主函数
main "$@"
