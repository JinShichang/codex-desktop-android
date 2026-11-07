package com.ai.codex;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
public final class DeviceFilesCheck {
    private static void denied(Path path)throws Exception{try{CodexDeviceFileRead.read(path.toString(),1024);throw new AssertionError(path.toString());}catch(java.io.IOException expected){}}
    public static void main(String[] args)throws Exception{
        Path root=Files.createTempDirectory("device-files-check-");
        try{
            Path file=root.resolve("项目😀.txt");Files.writeString(file,"hello 手机");
            if(!new String(CodexDeviceFileRead.read(file.toString(),1024),StandardCharsets.UTF_8).equals("hello 手机"))throw new AssertionError();
            Path link=root.resolve("link");Files.createSymbolicLink(link,file);denied(link);
            Path nested=root.resolve("nested");Files.createDirectory(nested);Files.writeString(nested.resolve("data"),"secret");
            Path dirlink=root.resolve("directory-link");Files.createSymbolicLink(dirlink,nested);denied(dirlink.resolve("data"));
            try{CodexDeviceFileRead.list(dirlink.toString(),257);throw new AssertionError();}catch(java.io.IOException expected){}
            denied(root);Files.writeString(root.resolve("large"),"x".repeat(2048));denied(root.resolve("large"));
            if(CodexDeviceFileRead.list(root.toString(),257).length!=5)throw new AssertionError();
            try(java.io.FileOutputStream output=new java.io.FileOutputStream(root.resolve("exported").toFile())){
                java.lang.reflect.Field field=java.io.FileDescriptor.class.getDeclaredField("fd");field.setAccessible(true);
                int fd=field.getInt(output.getFD());
                long bytes=CodexDeviceFileRead.copy(file.toString(),fd,1024);
                if(bytes!="hello 手机".getBytes(StandardCharsets.UTF_8).length)throw new AssertionError();
                try{CodexDeviceFileRead.copy(link.toString(),fd,1024);throw new AssertionError();}catch(java.io.IOException expected){}
                try{CodexDeviceFileRead.copy(file.toString(),fd,1);throw new AssertionError();}catch(java.io.IOException expected){}
            }
            if(!Files.readString(root.resolve("exported")).equals("hello 手机"))throw new AssertionError();
            System.out.println("Descriptor file tests passed: Unicode, final/intermediate symlink, directory, size bound, listing");
        }finally{try(var paths=Files.walk(root)){for(Path path:paths.sorted(java.util.Comparator.reverseOrder()).toList())Files.delete(path);}}
    }
}
