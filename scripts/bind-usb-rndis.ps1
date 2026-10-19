param([switch]$Install, [switch]$ClassOnly)
$ErrorActionPreference = 'Stop'
$paperosDeviceId = ''
if (-not $ClassOnly) {
    $paperosNode = @(Get-PnpDevice -PresentOnly | Where-Object InstanceId -like 'USB\VID_0525&PID_A4A2\*')
    if ($paperosNode.Count -ne 1) { throw 'Expected exactly one temporary PaperOS USB gadget' }
    $paperosProduct = (Get-PnpDeviceProperty -InstanceId $paperosNode[0].InstanceId -KeyName DEVPKEY_Device_BusReportedDeviceDesc).Data
    if ($paperosProduct -ne 'PaperOS-USB-Debug') { throw 'Device is not the workspace temporary USB gadget' }
    $paperosDeviceId = $paperosNode[0].InstanceId
}
$paperosSource = @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class PaperOSRndis {
 [StructLayout(LayoutKind.Sequential)] struct Device {
  public uint Size; public Guid Class; public uint DevInst; public UIntPtr Reserved;
 }
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Params {
  public uint Size, Flags, FlagsEx; public IntPtr Parent, Handler, Context, Queue;
  public UIntPtr ClassReserved; public uint Reserved;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string Path;
 }
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Driver {
  public uint Size, Type; public UIntPtr Reserved;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string Description;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string Manufacturer;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string Provider;
  public System.Runtime.InteropServices.ComTypes.FILETIME Date; public ulong Version;
 }
 [DllImport("setupapi.dll", SetLastError=true)] static extern IntPtr SetupDiCreateDeviceInfoList(ref Guid g, IntPtr p);
 [DllImport("setupapi.dll", SetLastError=true)] static extern IntPtr SetupDiCreateDeviceInfoList(IntPtr g, IntPtr p);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiOpenDeviceInfoW(IntPtr h, string id, IntPtr p, uint f, ref Device d);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiGetDeviceInstallParamsW(IntPtr h, IntPtr d, ref Params p);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiSetDeviceInstallParamsW(IntPtr h, IntPtr d, ref Params p);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiGetDeviceInstallParamsW(IntPtr h, ref Device d, ref Params p);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiSetDeviceInstallParamsW(IntPtr h, ref Device d, ref Params p);
 [DllImport("setupapi.dll", SetLastError=true)] static extern bool SetupDiBuildDriverInfoList(IntPtr h, IntPtr d, uint t);
 [DllImport("setupapi.dll", SetLastError=true)] static extern bool SetupDiBuildDriverInfoList(IntPtr h, ref Device d, uint t);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiEnumDriverInfoW(IntPtr h, ref Device d, uint t, uint i, ref Driver r);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiEnumDriverInfoW(IntPtr h, IntPtr d, uint t, uint i, ref Driver r);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiSetSelectedDriverW(IntPtr h, ref Device d, ref Driver r);
 [DllImport("setupapi.dll", SetLastError=true)] static extern bool SetupDiCallClassInstaller(uint f, IntPtr h, ref Device d);
 [DllImport("setupapi.dll")] static extern bool SetupDiDestroyDeviceInfoList(IntPtr h);
 static void Check(bool ok, string op) { if(!ok) throw new Win32Exception(Marshal.GetLastWin32Error(), op); }
 public static string[] Execute(string id, bool install) {
  // The existing gadget was misclassified as Ports, so accept any class here.
  // The driver list is still restricted to the built-in netrndis INF.
  IntPtr h = SetupDiCreateDeviceInfoList(IntPtr.Zero, IntPtr.Zero);
  if(h == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
  try {
   Device d = new Device(); d.Size=(uint)Marshal.SizeOf(typeof(Device));
   Params p = new Params(); p.Size=(uint)Marshal.SizeOf(typeof(Params));
   Check(SetupDiGetDeviceInstallParamsW(h,IntPtr.Zero,ref p),"get class params");
   p.Flags |= 0x00010000; p.FlagsEx |= 0x00000800; p.Path=Environment.GetFolderPath(Environment.SpecialFolder.Windows)+"\\INF\\netrndis.inf";
   Check(SetupDiSetDeviceInstallParamsW(h,IntPtr.Zero,ref p),"set built-in INF");
   Check(SetupDiBuildDriverInfoList(h,IntPtr.Zero,1),"build global RNDIS drivers");
   if(String.IsNullOrEmpty(id)) {
    var globalNames = new List<string>();
    for(uint i=0;;i++) {
     Driver r = new Driver(); r.Size=(uint)Marshal.SizeOf(typeof(Driver));
     if(!SetupDiEnumDriverInfoW(h,IntPtr.Zero,1,i,ref r)) { if(Marshal.GetLastWin32Error()!=259) Check(false,"enumerate class drivers"); break; }
     globalNames.Add(r.Description+" | "+r.Provider);
    }
    return globalNames.ToArray();
   }
   Check(SetupDiOpenDeviceInfoW(h,id,IntPtr.Zero,0,ref d),"open gadget");
   Params deviceParams = new Params(); deviceParams.Size=(uint)Marshal.SizeOf(typeof(Params));
   Check(SetupDiGetDeviceInstallParamsW(h,ref d,ref deviceParams),"get device params");
   deviceParams.Flags |= 0x00800000;
   Check(SetupDiSetDeviceInstallParamsW(h,ref d,ref deviceParams),"set quiet device install");
   var names = new List<string>(); Driver selected = new Driver(); bool found=false;
   for(uint i=0;;i++) {
    Driver r = new Driver(); r.Size=(uint)Marshal.SizeOf(typeof(Driver));
    if(!SetupDiEnumDriverInfoW(h,IntPtr.Zero,1,i,ref r)) { if(Marshal.GetLastWin32Error()!=259) Check(false,"enumerate drivers"); break; }
    names.Add(r.Description+" | "+r.Provider);
    if(r.Description.Contains("RNDIS6") && r.Provider.Contains("Microsoft")) { selected=r; found=true; }
   }
   if(install) {
    if(!found) throw new InvalidOperationException("Built-in RNDIS6 driver was not found");
    Check(SetupDiSetSelectedDriverW(h,ref d,ref selected),"select built-in RNDIS6 driver");
    Check(SetupDiCallClassInstaller(2,h,ref d),"install built-in RNDIS6 driver");
    names.Add("Installed built-in RNDIS6 for the verified PaperOS gadget only");
   }
   return names.ToArray();
  } finally { SetupDiDestroyDeviceInfoList(h); }
 }
}
'@
Add-Type -TypeDefinition $paperosSource
[PaperOSRndis]::Execute($paperosDeviceId, $Install.IsPresent)
