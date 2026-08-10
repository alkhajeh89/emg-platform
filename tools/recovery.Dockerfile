FROM postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777

RUN apk add --no-cache bash=5.3.9-r1 python3=3.14.5-r0 coreutils=9.11-r0 \
    && addgroup -g 10001 emg \
    && adduser -D -H -u 10001 -G emg emg
COPY tools/backup /opt/emg/backup
RUN chmod 0555 /opt/emg/backup/*.sh /opt/emg/backup/*.py
USER 10001:10001
ENTRYPOINT ["/opt/emg/backup/scheduled-backup.sh"]
