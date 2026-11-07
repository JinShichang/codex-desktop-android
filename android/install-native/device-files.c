#define _GNU_SOURCE
#include <jni.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

static void fail(JNIEnv *env) {
    jclass type = (*env)->FindClass(env, "java/io/IOException");
    if (type) (*env)->ThrowNew(env,type,"device_file_unavailable_or_unsafe");
}
static int open_path(JNIEnv *env, jbyteArray input, int directory) {
    jsize size=(*env)->GetArrayLength(env,input);
    if (size<1 || size>4096) { fail(env); return -1; }
    char *path=calloc((size_t)size+1,1);
    if (!path) { fail(env); return -1; }
    (*env)->GetByteArrayRegion(env,input,0,size,(jbyte*)path);
    if ((*env)->ExceptionCheck(env)) { free(path); return -1; }
    if (memchr(path,0,(size_t)size)) { free(path); fail(env); return -1; }
    int fd = -1;
    if (path[0] != '/' || strlen(path) > 4096) goto done;
    fd = open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if (fd < 0) goto done;
    char *cursor = path+1, *part;
    while ((part = strsep(&cursor,"/")) != NULL) {
        if (!*part) continue;
        if (!strcmp(part,".") || !strcmp(part,"..")) { close(fd); fd=-1; break; }
        int flags = O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK;
        if ((cursor && *cursor) || directory) flags |= O_DIRECTORY;
        int next = openat(fd,part,flags); close(fd); fd=next;
        if (fd < 0) break;
    }
done:
    free(path); if (fd < 0) fail(env); return fd;
}
JNIEXPORT jbyteArray JNICALL Java_com_ai_codex_FoldDeviceFileRead_readUtf8(JNIEnv *env,jclass type,jbyteArray path,jint limit) {
    (void)type;
    if (limit < 1 || limit > 1048576) { fail(env); return NULL; }
    int fd = open_path(env,path,0); if (fd < 0) return NULL;
    struct stat st;
    if (fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size > limit) { close(fd); fail(env); return NULL; }
    char *data = malloc((size_t)limit+1); if (!data) { close(fd); fail(env); return NULL; }
    size_t size=0; int error=0;
    while (size <= (size_t)limit) {
        ssize_t n = read(fd,data+size,(size_t)limit+1-size);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { error=1; break; }
        if (!n) break;
        size += (size_t)n;
    }
    close(fd);
    jbyteArray result=NULL;
    if (error || size > (size_t)limit) fail(env);
    else { result=(*env)->NewByteArray(env,(jsize)size); if (result) (*env)->SetByteArrayRegion(env,result,0,(jsize)size,(jbyte*)data); }
    free(data); return result;
}
JNIEXPORT jobjectArray JNICALL Java_com_ai_codex_FoldDeviceFileRead_listUtf8(JNIEnv *env,jclass type,jbyteArray path,jint limit) {
    (void)type;
    if (limit < 1 || limit > 257) { fail(env); return NULL; }
    int fd = open_path(env,path,1); if (fd < 0) return NULL;
    DIR *dir = fdopendir(fd); if (!dir) { close(fd); fail(env); return NULL; }
    char **names=calloc((size_t)limit,sizeof(char*));
    if (!names) { closedir(dir); fail(env); return NULL; }
    int count=0, error=0;
    while (count < limit) {
        errno=0; struct dirent *entry=readdir(dir);
        if (!entry) { if (errno) error=1; break; }
        if (!strcmp(entry->d_name,".") || !strcmp(entry->d_name,"..")) continue;
        names[count]=strdup(entry->d_name); if (!names[count]) { error=1; break; } count++;
    }
    closedir(dir);
    jobjectArray result=NULL;
    if (error) fail(env);
    else {
        jclass bytes=(*env)->FindClass(env,"[B");
        if (bytes) result=(*env)->NewObjectArray(env,count,bytes,NULL);
        if (result) for (int i=0;i<count;i++) {
            jsize size=(jsize)strlen(names[i]); jbyteArray name=(*env)->NewByteArray(env,size);
            if (!name) break;
            (*env)->SetByteArrayRegion(env,name,0,size,(jbyte*)names[i]);
            (*env)->SetObjectArrayElement(env,result,i,name); (*env)->DeleteLocalRef(env,name);
        }
    }
    for (int i=0;i<count;i++) free(names[i]);
    free(names); return result;
}

JNIEXPORT jlong JNICALL Java_com_ai_codex_FoldDeviceFileRead_copyUtf8(JNIEnv *env,jclass type,jbyteArray path,jint output,jlong limit) {
    (void)type;
    if (limit<1 || limit>134217728 || output<0) { fail(env); return -1; }
    int source=open_path(env,path,0); if (source<0) return -1;
    struct stat st;
    if (fstat(source,&st) || !S_ISREG(st.st_mode) || st.st_size>limit) { close(source); fail(env); return -1; }
    char buffer[16384]; jlong total=0; int error=0;
    for (;;) {
        ssize_t count=read(source,buffer,sizeof(buffer));
        if (count<0 && errno==EINTR) continue;
        if (count<0) { error=1; break; }
        if (!count) break;
        if (total+count>limit) { error=1; break; }
        ssize_t offset=0;
        while (offset<count) {
            ssize_t written=write(output,buffer+offset,(size_t)(count-offset));
            if (written<0 && errno==EINTR) continue;
            if (written<=0) { error=1; break; }
            offset+=written;
        }
        if (error) break;
        total+=count;
    }
    close(source); if (error) { fail(env); return -1; } return total;
}
